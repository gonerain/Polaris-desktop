import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';
import { BridgeClient } from '../integrations/client.mjs';
import { metadata, Session } from '../integrations/codex/session.mjs';

const root = resolve(import.meta.dirname, '..');
const definitions = JSON.parse(readFileSync(join(root, 'integrations/tools.json'), 'utf8'));

test('Codex lifecycle preserves active runs and deduplicates Stop', () => {
    const events = [];
    const first = metadata({ hook_event_name: 'SessionStart', session_id: 'test', cwd: root, prompt: 'private' });
    assert.equal(JSON.stringify(first).includes('private'), false);
    const state = new Session({ event: (event, data) => events.push({ event, data }) }, first);
    state.handle(first);
    const turn = { ...first, event: 'UserPromptSubmit', turn: 'turn-1' };
    state.handle(turn);
    state.handle({ ...first });
    assert.equal(state.runId, 'turn-1');
    state.handle({ ...turn, event: 'Stop' });
    state.handle({ ...turn, event: 'Stop' });
    assert.equal(events.filter(row => row.event === 'run.ended').length, 1);
    assert.equal(events.find(row => row.event === 'run.ended').data.outcome, 'unknown');
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
hub = AgentHub()
registry = ComponentRegistry()
store = CalendarTaskStore()
registry.register('calendar', CalendarAPI(store))
bridge = LocalBridge(hub, registry)
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
    } finally {
        client.stop();
        child.kill();
        if (child.exitCode === null && child.signalCode === null) await once(child, 'exit');
        lines.close();
        assert.equal(dirname(directory), fixtures);
        rmSync(directory, { recursive: true, force: true });
    }
});
