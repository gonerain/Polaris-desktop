import test from 'node:test';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { access, mkdtemp, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { BridgeClient } from '../client.mjs';
import { install } from '../pi/runtime.mjs';

const python = process.env.POLARIS_TEST_PYTHON || resolve('.venv/bin/python');
const agentDirectory = fileURLToPath(new URL('../../', import.meta.url));
const fixture = `
import json, sys
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(agentDirectory)})
from polaris_agent.model import AgentStore
from polaris_agent.bridge import Bridge
root=Path(sys.argv[1])
store=AgentStore(root/'store.json')
bridge=Bridge(store, root/'bridge')
print(json.dumps({'endpoint':str(bridge.endpoint)}), flush=True)
try:
    for line in sys.stdin:
        request=json.loads(line)
        if request['op']=='send':
            row=store.sessions()[0]
            result=bridge.send(row['id'],request['text'],mode=request['mode'])
        elif request['op']=='delivery':
            result=store.delivery(request['id'])
        else:
            result=store.sessions()
        print(json.dumps(result),flush=True)
finally:
    bridge.close()
`;

test('real Python bridge and real Node Pi adapter agree on lifecycle, mark and send', async t => {
    try { await access(python); }
    catch { return t.skip('Set POLARIS_TEST_PYTHON or provide .venv/bin/python'); }
    const dir = await mkdtemp(join(tmpdir(), 'polaris-cross-language-'));
    const host = spawn(python, ['-u', '-c', fixture, dir], {stdio: ['pipe', 'pipe', 'pipe']});
    let diagnostics = '';
    host.stderr.on('data', chunk => { diagnostics += chunk; });
    const lines = createInterface({input: host.stdout});
    const incoming = lines[Symbol.asyncIterator]();
    const next = async () => {
        const item = await incoming.next();
        assert.equal(item.done, false, diagnostics);
        return JSON.parse(item.value);
    };
    const control = async frame => {
        host.stdin.write(JSON.stringify(frame) + '\n');
        return next();
    };
    let client, shutdown;
    try {
        const {endpoint} = await next();
        class ConnectedClient extends BridgeClient {
            constructor(options) { super({...options, endpoint}); client = this; }
        }
        const handlers = {}, tools = {}, messages = [];
        const pi = {
            on: (name, handler) => { handlers[name] = handler; },
            registerCommand() {},
            registerTool: tool => { tools[tool.name] = tool; },
            sendUserMessage: (text, options) => { messages.push({text, options}); },
        };
        install(pi, {}, ConnectedClient);
        const context = {
            cwd: dir, isIdle: () => true,
            sessionManager: {getSessionId: () => 'fixture-pi-session', getSessionName: () => 'Fixture chat'},
        };
        handlers.session_start({}, context);
        shutdown = handlers.session_shutdown;
        await once(client, 'connected');
        await tools.mark_current.execute('', {name: 'Explicit fixture name'});
        const rows = await control({op: 'sessions'});
        assert.equal(rows.length, 1);
        assert.equal(rows[0].marked, true);
        assert.equal(rows[0].sessionId, 'fixture-pi-session');
        handlers.agent_start();
        handlers.message_end({message: {role: 'assistant', stopReason: 'stop', content: [{type: 'text', text: 'Fixture final reply'}]}});
        handlers.agent_settled({aborted: false});
        const status = await client.request('session.status', {sessionId: 'fixture-pi-session'});
        assert.equal(status.runs.at(-1).status, 'completed');
        const result = await client.request('session.reply', {sessionId: 'fixture-pi-session'});
        assert.equal(result.reply, 'Fixture final reply');
        const delivery = await control({op: 'send', text: 'Fixture user text', mode: 'start'});
        // A same-connection request acts as a barrier after the host's command result.
        await client.request('session.status', {sessionId: 'fixture-pi-session'});
        const receipt = await control({op: 'delivery', id: delivery.id});
        assert.equal(receipt.status, 'accepted');
        assert.equal(messages[0].text, 'Fixture user text');
        assert.equal(messages[0].options.expandPromptTemplates, false);
    } finally {
        shutdown?.();
        client?.stop();
        host.stdin.end();
        const timer = setTimeout(() => host.kill(), 2000);
        await once(host, 'exit');
        clearTimeout(timer);
        lines.close();
        await rm(dir, {recursive: true, force: true});
    }
});
