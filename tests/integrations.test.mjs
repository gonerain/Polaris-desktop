import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { chmodSync, readFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { sendDesktopMessage } from '../integrations/codex/desktop-ipc.mjs';
import test from 'node:test';
import { BridgeClient } from '../integrations/client.mjs';
import { metadata, Session } from '../integrations/codex/session.mjs';

const root = resolve(import.meta.dirname, '..');
const definitions = JSON.parse(readFileSync(join(root, 'integrations/tools.json'), 'utf8'));

test('Codex lifecycle preserves active runs and deduplicates Stop', () => {
    const events = [];
    const first = metadata({ hook_event_name: 'SessionStart', session_id: 'test', cwd: root, prompt: 'private' });
    assert.equal(first.sessionId, 'test');
    assert.throws(() => metadata({ hook_event_name: 'SessionStart', session_id: 'x'.repeat(257) }), /Invalid hook/);
    assert.equal(JSON.stringify(first).includes('private'), false);
    const state = new Session({ event: (event, data) => events.push({ event, data }) }, first);
    state.handle(first);
    assert.equal(events[0].data.sessionId, 'test');
    const turn = { ...first, event: 'UserPromptSubmit', turn: 'turn-1' };
    state.handle(turn);
    state.handle({ ...first });
    assert.equal(state.runId, 'turn-1');
    const stopped = metadata({hook_event_name: 'Stop', session_id: 'test', turn_id: 'native-turn', last_assistant_message: '完成了\n下一步检查', prompt: 'private'});
    assert.equal(stopped.reply, '完成了\n下一步检查');
    assert.equal(JSON.stringify(stopped).includes('private'), false);
    assert.equal(metadata({hook_event_name: 'UserPromptSubmit', session_id: 'test', last_assistant_message: 'do not forward'}).reply, undefined);
    const longReply = metadata({hook_event_name: 'Stop', session_id: 'test', last_assistant_message: '🙂'.repeat(8001)});
    assert.equal(Array.from(longReply.reply).length, 8000);
    assert.equal(longReply.replyTruncated, true);
    const escapedReply = metadata({hook_event_name: 'Stop', session_id: 'test', cwd: '\u0001'.repeat(4096), last_assistant_message: '\u0001'.repeat(8000)});
    assert.ok(Buffer.byteLength(JSON.stringify(escapedReply)) <= 56000);
    assert.equal(escapedReply.replyTruncated, true);
    state.handle({ ...turn, event: 'Stop', reply: stopped.reply, replyTruncated: false });
    state.handle({ ...turn, event: 'Stop' });
    assert.equal(events.filter(row => row.event === 'run.ended').length, 1);
    assert.equal(events.find(row => row.event === 'run.ended').data.outcome, 'unknown');
    assert.equal(events.find(row => row.event === 'run.ended').data.reply, '完成了\n下一步检查');
    assert.equal(state.handle({ ...first, event: 'SessionEnd' }), false);
});

test('MCP publishes the shared schemas and validates tool arguments', { timeout: 10000 }, async () => {
    const child = spawn(process.execPath, ['integrations/codex/mcp.mjs'], {
        cwd: root, windowsHide: true,
        env: { ...process.env, POLARIS_RELAY: '', POLARIS_ENDPOINT: join(root, 'build/nonexistent-endpoint.json') },
        stdio: ['pipe', 'pipe', 'pipe'],
    });
    const lines = createInterface({ input: child.stdout });
    const replies = new Map();
    lines.on('line', line => {
        const message = JSON.parse(line);
        replies.get(message.id)?.(message);
        replies.delete(message.id);
    });
    const request = (id, method, params) => new Promise(resolve => {
        replies.set(id, resolve);
        child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
    try {
        assert.equal((await request(1, 'initialize', { protocolVersion: '2025-11-25' })).result.serverInfo.name, 'polaris');
        const listed = (await request(2, 'tools/list', {})).result.tools;
        assert.deepEqual(listed, definitions.map(({ method, ...tool }) => tool));
        for (const [i, args] of [null, [], { component: 'calendar', operation: 'task.list', args: [] }, { extra: true }].entries()) {
            const response = await request(i + 3, 'tools/call', { name: 'polaris_call', arguments: args });
            assert.equal(response.error?.code, -32602);
        }
        const response = await request(10, 'tools/call', { name: 'polaris_call', arguments: {
            component: 'calendar', operation: 'calendar.status',
        } });
        assert.equal(response.result.isError, true); // Valid optional args; only the connection is absent.
    } finally {
        child.stdin.end();
        child.kill();
        if (child.exitCode === null && child.signalCode === null) await once(child, 'exit');
        lines.close();
    }
});

test('Node client authenticates with the real Qt bridge and respects read grants', { timeout: 15000 }, async () => {
    const fixtures = join(root, 'build/test-bridge');
    mkdirSync(fixtures, { recursive: true });
    const directory = mkdtempSync(join(fixtures, 'case-'));
    const python = process.env.POLARIS_TEST_PYTHON || (process.platform === 'win32'
        ? join(root, '.venv/Scripts/python.exe') : join(root, '.venv/bin/python'));
    const code = `
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QTimer
from polaris.agents import AgentHub
from polaris.component_api import ComponentRegistry
from polaris.calendar_api import CalendarAPI
from polaris.tasks import CalendarTaskStore
from polaris.local_bridge import LocalBridge
app = QCoreApplication([])
from polaris.component_api import ApiError
probe = AgentHub()
probe.connect_client('owner', 'Fixture')
probe.snapshot('owner', {'sessionId': 'target', 'source': 'Fixture', 'name': 'Target', 'project': '', 'state': 'idle', 'sendModes': ['start']})
args = {'instanceId': 'owner', 'sessionId': 'target', 'text': 'exact text', 'mode': 'start'}
sent = probe.call('session.send', args)
try:
    probe.call('session.send', args)
    raise AssertionError('concurrent send accepted')
except ApiError as error:
    assert error.code == 'send_pending'
ack = {'deliveryId': sent['deliveryId'], 'sessionId': 'target', 'status': 'accepted', 'turnId': 'native-turn'}
try:
    probe.command_result('other-connection', ack)
    raise AssertionError('forged receipt accepted')
except ApiError as error:
    assert error.code == 'unknown_delivery'
probe._deliveries[sent['deliveryId']]['deadline'] = 0
assert probe.call('session.delivery', {'deliveryId': sent['deliveryId']})['status'] == 'unknown'
probe.command_result('owner', ack)
assert probe.call('session.delivery', {'deliveryId': sent['deliveryId']})['status'] == 'accepted'
sent = probe.call('session.send', args)
probe.disconnect_client('owner')
assert probe.call('session.delivery', {'deliveryId': sent['deliveryId']})['status'] == 'unknown'
# Last replies must belong to the matched completed run, never to a stale duplicate.
reply_args = {'instanceId': 'reply-owner', 'sessionId': 'reply-session'}
probe.connect_client('reply-owner', 'Reply fixture')
probe.snapshot('reply-owner', {'sessionId': 'reply-session', 'source': 'Fixture', 'name': 'Reply', 'project': '', 'state': 'running', 'runId': 'reply-turn'})
assert probe.call('session.reply', reply_args)['available'] is False
ended = {'sessionId': 'reply-session', 'runId': 'reply-turn', 'outcome': 'unknown', 'reply': 'Exact reply: 完成', 'replyTruncated': False}
try:
    probe.event('reply-owner', 'run.ended', {**ended, 'reply': 'x' * 8001})
    raise AssertionError('oversized reply accepted')
except ApiError as error:
    assert error.code == 'invalid_params'
probe.event('reply-owner', 'run.ended', ended)
reply = probe.call('session.reply', reply_args)
assert reply['reply'] == 'Exact reply: 完成' and reply['runId'] == 'reply-turn'
assert reply['truncated'] is False and reply['endedAt']
probe.event('reply-owner', 'run.ended', {**ended, 'reply': 'stale overwrite'})
assert probe.call('session.reply', reply_args)['reply'] == 'Exact reply: 完成'
probe.event('reply-owner', 'run.started', {'sessionId': 'reply-session', 'runId': 'next-turn'})
assert probe.call('session.reply', reply_args)['runId'] == 'reply-turn'
probe.event('reply-owner', 'run.ended', {'sessionId': 'reply-session', 'runId': 'next-turn', 'outcome': 'cancelled'})
assert probe.call('session.reply', reply_args)['available'] is False
assert probe.call('session.reply', reply_args)['runId'] == 'next-turn'
probe.disconnect_client('reply-owner')
assert probe.call('session.reply', reply_args)['reason'] == 'reply_not_reported'
# A plugin shares grants across connections, survives app restart, and can revoke offline.
import tempfile
with tempfile.TemporaryDirectory() as permission_dir:
    permissions = AgentHub()
    permissions.load_permissions(permission_dir)
    permissions.connect_client('first', 'Codex tools', 'polaris.codex')
    permissions.connect_client('second', 'Codex hooks', 'polaris.codex')
    permissions.connect_client('stranger', 'Codex tools', 'other.plugin')
    permissions.connect_client('temporary', 'Temporary client')
    permissions.connect_client('legacy-hook', 'Codex hooks')
    permissions.connect_client('legacy-tool', 'Codex tools')
    codex_rows = [row for row in permissions.clients if row.get('pluginId') == 'polaris.codex']
    assert len(codex_rows) == 1
    assert codex_rows[0]['name'] == 'Codex 插件'
    permissions.grant('plugin:polaris.codex', 'agents', 'read')
    assert permissions.grants('legacy-hook') == {'agents': 'read'}
    assert permissions.grants('legacy-tool') == {'agents': 'read'}
    assert permissions.grants('first') == {'agents': 'read'}
    assert permissions.grants('second') == {'agents': 'read'}
    assert permissions.grants('stranger') == {}
    assert permissions.grants('temporary') == {}
    permissions.disconnect_client('first')
    permissions.disconnect_client('second')
    permissions.disconnect_client('legacy-hook')
    permissions.disconnect_client('legacy-tool')
    assert any(row['instanceId'] == 'plugin:polaris.codex' for row in permissions.clients)
    restored = AgentHub()
    restored.load_permissions(permission_dir)
    restored.connect_client('third', 'Codex tools', 'polaris.codex')
    assert restored.grants('third') == {'agents': 'read'}
    restored.disconnect_client('third')
    restored.grant('plugin:polaris.codex', 'agents', 'none')
    restored_again = AgentHub()
    restored_again.load_permissions(permission_dir)
    restored_again.connect_client('fourth', 'Codex tools', 'polaris.codex')
    restored_again.connect_client('old-after-revoke', 'Codex hooks')
    assert restored_again.grants('old-after-revoke') == {'agents': 'none'}
    assert restored_again.grants('fourth') == {'agents': 'none'}
hub = AgentHub()
registry = ComponentRegistry()
store = CalendarTaskStore()
registry.register('calendar', CalendarAPI(store))
registry.register('agents', hub)
class TestBridge(LocalBridge):
    def dispatch(self, peer, message):
        result = super().dispatch(peer, message)
        if message.get('method') == 'hello' and message['params']['name'] == 'Regression fixture':
            hub.grant(peer.instance, 'agents', 'write')
        return result
bridge = TestBridge(hub, registry)
bridge.start(Path(sys.argv[1]))
if not bridge.server.isListening():
    raise RuntimeError(hub.connectionError)
app.aboutToQuit.connect(bridge.stop)
QTimer.singleShot(12000, app.quit)
print('ready', flush=True)
app.exec()
`;
    const child = spawn(python, ['-X', 'utf8', '-B', '-c', code, directory], {
        cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    });
    const lines = createInterface({ input: child.stdout });
    let diagnostics = '';
    child.stderr.on('data', chunk => { diagnostics += chunk; });
    const client = new BridgeClient({ name: 'Regression fixture', endpoint: join(directory, 'bridge/endpoint.json') });
    try {
        await once(lines, 'line', { signal: AbortSignal.timeout(5000) }).catch(error => {
            throw new Error(`${error.message}: ${diagnostics}`);
        });
        client.start();
        await once(client, 'connected', { signal: AbortSignal.timeout(5000) }).catch(error => {
            throw new Error(`${error.message}: ${client.lastError}; ${diagnostics}`);
        });
        assert.equal((await client.request('components.list'))[0].id, 'calendar');
        assert.equal((await client.request('components.help', { component: 'calendar' })).version, 1);
        await assert.rejects(client.request('components.call', {
            component: 'calendar', operation: 'calendar.status',
        }), /permission_denied/);
        client.event('session.snapshot', { sessionId: 'regression', source: 'Test', name: 'Fixture', project: '', state: 'idle' });
        client.event('run.started', { sessionId: 'regression', runId: 'turn-1' });
        client.event('run.ended', { sessionId: 'regression', runId: 'turn-1', outcome: 'ended' });
        assert.equal((await client.request('heartbeat')).alive, true);
        const target = new BridgeClient({ name: 'Target fixture', instanceId: 'target-fixture', endpoint: join(directory, 'bridge/endpoint.json') });
        const received = [];
        target.on('command', command => {
            received.push(command);
            target.event('command.result', { deliveryId: command.id, sessionId: command.params.sessionId,
                status: 'accepted', turnId: 'native-turn' });
        });
        try {
            target.start();
            await once(target, 'connected', { signal: AbortSignal.timeout(5000) });
            target.event('session.snapshot', { sessionId: 'native-session', source: 'Fixture', name: 'Target', project: '', state: 'idle', sendModes: ['start'] });
            await target.request('heartbeat');
            const call = (operation, args) => client.request('components.call', { component: 'agents', operation, args });
            await assert.rejects(target.request('components.call', { component: 'agents', operation: 'session.send', args: {
                instanceId: 'target-fixture', sessionId: 'native-session', text: 'Denied', mode: 'start',
            } }), /permission_denied/);
            await assert.rejects(call('session.send', { instanceId: 'target-fixture', sessionId: 'native-session', text: 'Wrong mode', mode: 'steer' }), /unsupported/);
            const receipt = await call('session.send', { instanceId: 'target-fixture', sessionId: 'native-session', text: 'Exact message', mode: 'start' });
            let delivery;
            for (let i = 0; i < 20; i++) {
                delivery = await call('session.delivery', { deliveryId: receipt.deliveryId });
                if (delivery.status !== 'sending') break;
                await new Promise(resolve => setTimeout(resolve, 10));
            }
            assert.equal(delivery.status, 'accepted');
            assert.equal(delivery.turnId, 'native-turn');
            assert.equal(received.length, 1);
            assert.equal(received[0].params.text, 'Exact message');
            const replyArgs = {instanceId: 'target-fixture', sessionId: 'native-session'};
            target.event('run.started', {sessionId: 'native-session', runId: 'reply-native-turn'});
            target.event('run.ended', {sessionId: 'native-session', runId: 'reply-native-turn', outcome: 'unknown', reply: '真实桥测试正文\n第二行', replyTruncated: false});
            await target.request('heartbeat');
            await assert.rejects(target.request('components.call', {component: 'agents', operation: 'session.reply', args: replyArgs}), /permission_denied/);
            const reply = await call('session.reply', replyArgs);
            assert.equal(reply.reply, '真实桥测试正文\n第二行');
            assert.equal(reply.available, true);
            assert.equal(reply.runId, 'reply-native-turn');
            assert.equal(reply.truncated, false);
            const results = await call('result.list', {});
            assert.equal(results.results[0].replyAvailable, true);
            assert.equal(results.results[0].sessionId, 'native-session');

        } finally { target.stop(); }
    } finally {
        client.stop();
        child.kill();
        if (child.exitCode === null && child.signalCode === null) await once(child, 'exit');
        lines.close();
        assert.equal(dirname(directory), fixtures);
        rmSync(directory, { recursive: true, force: true });
    }
});


test('Codex desktop IPC routes exact text to owner and treats lost acknowledgement as unknown', { skip: process.platform !== 'linux', timeout: 10000 }, async () => {
    for (const mode of ['start', 'steer', 'lost', 'no-owner']) {
        const directory = mkdtempSync(join(tmpdir(), 'polaris-ipc-'));
        const path = join(directory, 'ipc.sock');
        const requests = [];
        const peers = new Set();
        const server = createServer(socket => {
            peers.add(socket); socket.on('close', () => peers.delete(socket));
            let buffer = Buffer.alloc(0);
            socket.on('data', chunk => {
                buffer = Buffer.concat([buffer, chunk]);
                while (buffer.length >= 4 && buffer.length >= 4 + buffer.readUInt32LE(0)) {
                    const size = buffer.readUInt32LE(0);
                    const request = JSON.parse(buffer.subarray(4, size + 4));
                    buffer = buffer.subarray(size + 4); requests.push(request);
                    let result;
                    if (request.method === 'initialize') result = { clientId: 'probe-client' };
                    else if (request.method === 'thread-owner-discovery') result = {};
                    else {
                        assert.equal(request.targetClientId, 'owner-client');
                        assert.equal(request.sourceClientId, 'probe-client');
                        const input = request.params.input || request.params.turnStart.request.input;
                        assert.equal(input[0].text, 'Exact 中文 message');
                        assert.equal(request.params.conversationId, 'native-session');
                        if (mode === 'lost') { socket.destroy(); continue; }
                        assert.equal(request.method, mode === 'start' ? 'thread-follower-start-turn' : 'thread-follower-steer-turn');
                        result = { result: mode === 'start' ? { turn: { id: 'native-turn' } } : { turnId: 'native-turn' } };
                    }
                    const reply = { type: 'response', requestId: request.requestId, resultType: 'success',
                        handledByClientId: 'owner-client', result };
                    if (mode === 'no-owner' && request.method === 'thread-owner-discovery') {
                        reply.resultType = 'error'; reply.error = 'no-client-found';
                    }
                    const body = Buffer.from(JSON.stringify(reply)), header = Buffer.alloc(4);
                    header.writeUInt32LE(body.length);
                    socket.write(header.subarray(0, 2));
                    socket.write(Buffer.concat([header.subarray(2), body]));
                }
            });
        });
        try {
            await new Promise(resolve => server.listen(path, resolve)); chmodSync(path, 0o600);
            const result = await sendDesktopMessage({ sessionId: 'native-session', text: 'Exact 中文 message',
                mode: mode === 'start' ? 'start' : 'steer', project: root, socketPath: path });
            assert.equal(result.status, mode === 'lost' ? 'unknown' : mode === 'no-owner' ? 'failed' : 'accepted');
            assert.equal(requests.length, mode === 'no-owner' ? 2 : 3);
            if (result.status === 'accepted') assert.equal(result.turnId, 'native-turn');
        } finally {
            for (const peer of peers) peer.destroy();
            await new Promise(resolve => server.close(resolve));
            rmSync(directory, { recursive: true, force: true });
        }
    }
});
