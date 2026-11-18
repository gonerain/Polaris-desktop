import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { access, mkdtemp, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { historyPage } from '../pi/runtime.mjs';

let sdk;
try { sdk = await import(process.env.POLARIS_TEST_PI_MODULE || '@earendil-works/pi-coding-agent'); }
catch (error) { if (process.env.POLARIS_TEST_PI_MODULE) throw error; }
const skip = !sdk && 'Set POLARIS_TEST_PI_MODULE to the installed Pi dist/index.js';
const assistant = (content, stopReason = 'stop') => ({role: 'assistant', content,
    api: 'bridge-test', provider: 'bridge-test', model: 'fixture', stopReason,
    usage: {input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}}, timestamp: Date.now()});
const words = value => [{type: 'text', text: value}];

function seed(manager, input, reply) {
    const first = manager.appendMessage({role: 'user', content: input, timestamp: Date.now()});
    const last = manager.appendMessage(assistant(words(reply)));
    return {first, last};
}

test('native history includes pre-compaction inputs, pages beyond 100 rounds and pins its branch', {skip}, () => {
    const manager = sdk.SessionManager.inMemory('/fixture');
    for (let i = 0; i < 105; i++) seed(manager, `input-${i}`, `reply-${i}`);
    const first = manager.getBranch()[0].id;
    manager.appendCompaction('COMPACTION SUMMARY IS NOT A REPLY', first, 100000);
    const firstPage = historyPage(manager, null, 100);
    assert.equal(firstPage.items[0].text, 'input-0');
    assert.equal(firstPage.items[1].finality, 'unknown');
    let cursor = firstPage.nextCursor, items = [...firstPage.items];
    seed(manager, 'APPENDED AFTER SNAPSHOT', 'later');
    while (cursor) {
        const page = historyPage(manager, cursor, 100);
        items.push(...page.items); cursor = page.nextCursor;
    }
    assert.equal(items.length, 210);
    assert.equal(items.at(-1).text, 'reply-104');
    assert.equal(items.some(item => item.text.includes('COMPACTION SUMMARY')), false);
    manager.branch(first);
    seed(manager, 'OTHER BRANCH', 'branch reply');
    assert.throws(() => historyPage(manager, firstPage.nextCursor), /history_branch_changed/);
    assert.deepEqual(historyPage(manager).items.map(item => item.text), ['input-0', 'OTHER BRANCH', 'branch reply']);
    assert.throws(() => historyPage(manager, 'broken cursor'), /invalid_history_cursor/);
});

test('native end markers select only the final reply, including across steering and continuation', {skip}, () => {
    const manager = sdk.SessionManager.inMemory('/fixture');
    manager.appendMessage({role: 'user', content: 'first', timestamp: Date.now()});
    manager.appendMessage(assistant(words('INTERMEDIATE STOP')));
    manager.appendMessage({role: 'user', content: 'steer', timestamp: Date.now()});
    manager.appendMessage(assistant([...words('TOOL PROGRESS'), {type: 'toolCall', id: 'tool', name: 'read', arguments: {}}], 'toolUse'));
    const finalEntryId = manager.appendMessage(assistant(words('FINAL')));
    manager.appendCustomEntry('polaris.bridge.run-ended', {runId: 'exact-run', startEntryId: null, finalEntryId, status: 'completed'});
    const page = historyPage(manager);
    assert.deepEqual(page.items.map(item => item.text), ['first', 'steer', 'FINAL']);
    assert.equal(page.items[2].finality, 'confirmed');
    assert.ok(page.items.every(item => item.runId === 'exact-run'));
    const activeStart = manager.getLeafId();
    seed(manager, 'new input', 'NOT SETTLED');
    const active = {runId: 'active', startEntryId: activeStart, started: true};
    assert.equal(historyPage(manager, null, 50, active).items.some(item => item.text === 'NOT SETTLED'), false);
});

const python = process.env.POLARIS_TEST_PYTHON || resolve('.venv/bin/python');
const directory = fileURLToPath(new URL('../../', import.meta.url));
const fixture = `
import json,sys
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(directory)})
from polaris_agent.model import AgentStore
from polaris_agent.bridge import Bridge
from polaris_agent.completion import Completions
root=Path(sys.argv[1]); store=AgentStore(root/'store.json'); bridge=Bridge(store,root/'bridge')
callbacks=[]
class Authority:
    def call(self,target,operation,params):
        callbacks.append(params['result']); return {'accepted':True}
    def forget_task(self,task): pass
class Component:
    def resume_task(self,task): return Authority()
component=Component(); component.store=store; component.bridge=bridge
completions=Completions(component)
print(json.dumps({'endpoint':str(bridge.endpoint)}),flush=True)
try:
    for line in sys.stdin:
        q=json.loads(line)
        if q['op']=='sessions': result=store.sessions()
        elif q['op']=='connection': result=next((id(p) for p in bridge.peers.values()),None)
        elif q['op']=='send':
            row=store.sessions()[0]
            result=bridge.send(row['id'],q['text'],mode=q['mode'],on_complete={'target':'fixture-receiver','operation':'done','params':{}})
        elif q['op']=='delivery': result=store.delivery(q['id'])
        elif q['op']=='history': result=bridge.history(store.sessions()[0]['id'],q.get('cursor'),q.get('limit',50))
        elif q['op']=='flush':
            completions.flush(); result=callbacks
        elif q['op']=='events': result=store.notifications['events']
        print(json.dumps(result),flush=True)
finally: bridge.close()
`;

const deferred = () => {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return {promise, resolve};
};

test('installed Pi loads the actual extension, sends/steers, returns history and calls real Python completions',
    {skip, timeout: 20000}, async t => {
    try { await access(python); } catch { return t.skip('Set POLARIS_TEST_PYTHON'); }
    const dir = await mkdtemp(join(tmpdir(), 'polaris-pi-sdk-'));
    const host = spawn(python, ['-u', '-c', fixture, dir], {stdio: ['pipe', 'pipe', 'pipe']});
    let diagnostics = '';
    host.stderr.on('data', chunk => { diagnostics += chunk; });
    const lines = createInterface({input: host.stdout});
    const iterator = lines[Symbol.asyncIterator]();
    const read = async () => {
        const line = await iterator.next();
        assert.equal(line.done, false, diagnostics);
        return JSON.parse(line.value);
    };
    const control = async value => { host.stdin.write(JSON.stringify(value) + '\n'); return read(); };
    let session;
    const oldEndpoint = process.env.POLARIS_AGENT_ENDPOINT;
    try {
        process.env.POLARIS_AGENT_ENDPOINT = (await read()).endpoint;
        const model = {id: 'fixture', name: 'Fixture', provider: 'bridge-test', api: 'bridge-test', baseUrl: 'http://unused.invalid',
            reasoning: false, input: ['text'], contextWindow: 100000, maxTokens: 1000,
            cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0}};
        const runtime = await sdk.ModelRuntime.create({authPath: join(dir, 'auth.json'), modelsPath: join(dir, 'models.json')});
        let calls = 0, release = deferred(), started = deferred();
        let behavior = 'normal', continuationCalls = 0, continued = false;
        const intercepted = deferred();
        runtime.registerProvider('bridge-test', {api: 'bridge-test', apiKey: 'fixture-key', models: [model],
            streamSimple: () => {
                let message;
                if (behavior === 'error') message = {...assistant([], 'error'), errorMessage: 'Fixture provider failure'};
                else if (behavior === 'continuation') message = assistant(words(continuationCalls++ === 0 ? 'CANDIDATE STOP' : 'CONTINUED FINAL'));
                else if (calls++ % 2 === 0) message = assistant([...words('PROCESS NOT EXPORTED'),
                    {type: 'toolCall', id: `call-${calls}`, name: 'wait_step', arguments: {}}], 'toolUse');
                else message = assistant(words('NATIVE FINAL'));
                return {async *[Symbol.asyncIterator]() {
                    yield {type: 'start', partial: message};
                    yield {type: message.stopReason === 'error' ? 'error' : 'done', reason: message.stopReason,
                        ...(message.stopReason === 'error' ? {error: message} : {message})};
                }, result: async () => message};
            }});
        const settings = sdk.SettingsManager.inMemory({compaction: {enabled: false}, retry: {enabled: false}});
        const manager = sdk.SessionManager.create(dir, join(dir, 'sessions'));
        seed(manager, 'BEFORE PLUGIN', 'OLD REPLY');
        const loader = new sdk.DefaultResourceLoader({cwd: dir, agentDir: dir, settingsManager: settings,
            additionalExtensionPaths: [fileURLToPath(new URL('../pi/polaris.ts', import.meta.url))],
            noSkills: true, noPromptTemplates: true, noThemes: true,
            extensionFactories: [pi => {
                pi.on('input', event => {
                    if (behavior === 'handled' && event.source === 'extension') {
                        intercepted.resolve();
                        return {action: 'handled'};
                    }
                });
                pi.on('agent_before_settle', () => {
                    if (behavior === 'continuation' && !continued) {
                        continued = true;
                        return {continue: true, entries: [{type: 'custom_message', customType: 'fixture-continuation',
                            content: 'Continue the same activity', display: false}]};
                    }
                });
            }]});
        await loader.reload();
        assert.deepEqual(loader.getExtensions().errors, []);
        ({session} = await sdk.createAgentSession({cwd: dir, agentDir: dir, modelRuntime: runtime, model,
            resourceLoader: loader, sessionManager: manager, settingsManager: settings, noTools: true,
            customTools: [{name: 'wait_step', label: 'Wait', description: 'Test barrier', parameters: {type: 'object', properties: {}},
                execute: async (_id, _params, signal) => {
                    started.resolve();
                    await Promise.race([release.promise, new Promise(done => signal.addEventListener('abort', done, {once: true}))]);
                    return {content: words('TOOL OUTPUT NOT EXPORTED'), details: {}};
                }}]}));
        const extensionErrors = [];
        await session.bindExtensions({onError: error => extensionErrors.push(error)});
        let rows;
        for (let i = 0; i < 100; i++) {
            rows = await control({op: 'sessions'});
            if (rows.length) break;
            await new Promise(done => setTimeout(done, 10));
        }
        assert.equal(rows.length, 1);
        await session.prompt('/polaris mark Native fixture');
        const before = await control({op: 'history'});
        assert.deepEqual(before.items.map(item => item.text), ['BEFORE PLUGIN', 'OLD REPLY']);
        const delivery = await control({op: 'send', text: 'REMOTE START', mode: 'start'});
        await started.promise;
        const receipt = await control({op: 'delivery', id: delivery.id});
        assert.equal(receipt.status, 'accepted');
        const steer = await control({op: 'send', text: 'REMOTE STEER', mode: 'steer'});
        // Wait for the actual host queue, not just extension dispatch.
        for (let i = 0; i < 100 && session.pendingMessageCount === 0; i++) await new Promise(done => setTimeout(done, 5));
        assert.equal(session.pendingMessageCount, 1);
        release.resolve();
        await session.waitForIdle();
        const history = await control({op: 'history'});
        assert.deepEqual(history.items.map(item => item.text), ['BEFORE PLUGIN', 'OLD REPLY', 'REMOTE START', 'REMOTE STEER', 'NATIVE FINAL']);
        assert.equal(history.items.at(-1).runId, receipt.runId);
        assert.equal(history.items.at(-1).finality, 'confirmed');
        assert.equal((await control({op: 'delivery', id: steer.id})).runId, receipt.runId);
        const callbacks = await control({op: 'flush'});
        assert.equal(callbacks.length, 2);
        assert.ok(callbacks.every(callback => callback.runId === receipt.runId && callback.reply === 'NATIVE FINAL'));
        assert.equal((await control({op: 'flush'})).length, 2);
        let events = await control({op: 'events'});
        assert.deepEqual(events.filter(event => event.runId === receipt.runId).map(event => event.event),
            ['run.started', 'run.input', 'run.input', 'run.ended']);
        assert.equal(JSON.stringify(events).includes('PROCESS NOT EXPORTED'), false);
        assert.equal(JSON.stringify(events).includes('TOOL OUTPUT NOT EXPORTED'), false);
        // Dispatch can be handled without starting a run. A later local run
        // must never complete that delivery or inherit its reserved identity.
        behavior = 'handled';
        const handled = await control({op: 'send', text: 'HANDLED WITHOUT EXECUTION', mode: 'start'});
        await intercepted.promise;
        const handledReceipt = await control({op: 'delivery', id: handled.id});
        behavior = 'normal';
        await session.prompt('NEXT LOCAL INPUT');
        await control({op: 'history'});
        events = await control({op: 'events'});
        assert.notEqual(events.at(-1).runId, handledReceipt.runId);
        assert.equal((await control({op: 'flush'})).length, 2);
        behavior = 'continuation';
        await session.prompt('LOCAL CONTINUATION');
        const continuedHistory = await control({op: 'history'});
        assert.equal(continuedHistory.items.some(item => item.text === 'CANDIDATE STOP'), false, JSON.stringify(continuedHistory));
        assert.equal(continuedHistory.items.at(-1).text, 'CONTINUED FINAL');
        events = await control({op: 'events'});
        assert.equal(events.at(-1).reply, 'CONTINUED FINAL');
        assert.equal(events.filter(event => event.runId === events.at(-1).runId && event.event === 'run.ended').length, 1);
        behavior = 'normal';
        // Native abort while a real SDK tool is waiting.
        release = deferred(); started = deferred();
        const aborted = session.prompt('LOCAL ABORT');
        await started.promise;
        await session.abort();
        await aborted;
        await control({op: 'history'}); // Also drains earlier lifecycle frames on the same connection.
        events = await control({op: 'events'});
        assert.equal(events.at(-1).status, 'stopped');
        assert.equal(events.at(-1).reply, null);
        behavior = 'error';
        await session.prompt('LOCAL ERROR');
        await control({op: 'history'});
        events = await control({op: 'events'});
        assert.equal(events.at(-1).status, 'failed');
        assert.equal(events.at(-1).reply, null);
        const eventCount = events.length;
        const connection = await control({op: 'connection'});
        await session.reload();
        for (let i = 0; i < 100; i++) {
            const replacement = await control({op: 'connection'});
            rows = await control({op: 'sessions'});
            if (replacement && replacement !== connection && rows[0].online) break;
            await new Promise(done => setTimeout(done, 10));
        }
        const reloaded = await control({op: 'history'});
        assert.deepEqual(reloaded.items, historyPage(manager).items);
        assert.equal(rows[0].title, 'Native fixture');
        assert.equal((await control({op: 'events'})).length, eventCount);
        assert.equal((await control({op: 'flush'})).length, 2);
        assert.deepEqual(extensionErrors, []);
    } finally {
        if (session) await session.extensionRunner.emit({type: 'session_shutdown', reason: 'quit'});
        session?.dispose();
        if (oldEndpoint === undefined) delete process.env.POLARIS_AGENT_ENDPOINT;
        else process.env.POLARIS_AGENT_ENDPOINT = oldEndpoint;
        host.stdin.end();
        await once(host, 'exit');
        lines.close();
        await rm(dir, {recursive: true, force: true});
    }
});
