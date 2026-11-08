// Short synchronous hook -> private local pipe -> persistent per-session bridge.
import { createConnection, createServer } from 'node:net';
import { mkdir, lstat, readFile } from 'node:fs/promises';
import { join, isAbsolute, basename, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { BridgeClient } from '../client.mjs';
import { digest, metadata, Session } from './session.mjs';
import { sendDesktopMessage, sendModes } from './desktop-ipc.mjs';
import { waitForInteraction, permissionPrompt } from './interactions.mjs';

const MAX = 65536;
const currentVersion = '0.3.0';
let hookOutput = {};
const build = digest((await Promise.all(['./hook.mjs','./session.mjs','./desktop-ipc.mjs','./interactions.mjs','../client.mjs'].map(name => readFile(new URL(name, import.meta.url))))).map(b=>b.toString()).join('\0'));
const upgrade = process.argv[2] === '--upgrade-helpers';
const statusOnly = process.argv[2] === '--helper-status';
const controlMode = upgrade || statusOnly;
const daemon = process.argv[2] === '--daemon';
if (process.argv[2]==='--mark') setTimeout(() => process.exit(1),7000).unref();

async function address(sessionId, {create = true} = {}) {
    const base = process.platform === 'win32' ? process.env.LOCALAPPDATA : (process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'));
    const root = process.env.POLARIS_AGENT_CODEX_DATA || join(base, 'polaris-agent', 'codex-hosts');
    if (create) await mkdir(root, { recursive: true, mode: 0o700 });
    const info = await lstat(root);
    if (!info.isDirectory() || info.isSymbolicLink() || (process.platform !== 'win32' &&
        (info.uid !== process.getuid() || (info.mode & 0o077)))) throw new Error('Private plugin data required');
    const key = digest(root + sessionId).slice(0, 40);
    return process.platform === 'win32' ? `\\\\.\\pipe\\polaris-codex-${key}` : join(root, `c-${key}.sock`);
}

async function forward(path, data) {
    return await new Promise((resolve, reject) => {
        const socket = createConnection(path);
        let buffer='';
        socket.setTimeout(data.event==='Interaction'?115000:data.event==='Mark'?6000:700, () => socket.destroy(new Error('Hook delivery timeout')));
        socket.on('error', reject);
        socket.on('connect', () => socket.write(JSON.stringify(data) + '\n'));
        socket.on('data', chunk => {
            buffer += chunk.toString();
            if (Buffer.byteLength(buffer)>MAX) return socket.destroy(new Error('Helper response too large'));
            if (!buffer.includes('\n')) return;
            socket.end();
            try { const reply=JSON.parse(buffer.split('\n')[0]); reply.error ? reject(Error(reply.error)) : resolve(reply); }
            catch {reject(Error('Invalid helper response'));}
        });
        socket.on('end', () => { if (!buffer) reject(Error('Helper closed')); });
    });
}

async function start(path, initial) {
    const client = new BridgeClient({ adapter: 'codex', clientId: initial.sessionId });
    const state = new Session(client, initial);
    if (typeof initial.title === 'string') state.title = initial.title;
    state.sendModes = sendModes;
    const deliveries = new Set();
    let sending = false, retiring = false;
    const interactions = new Set();
    let replaceAfterStop = false, replacementScript = fileURLToPath(import.meta.url);
    client.on('command', async command => {
        if (command.command !== 'session.send' || deliveries.has(command.requestId)) return;
        deliveries.add(command.requestId);
        let result;
        if (command.sessionId !== state.sessionId || sending || retiring) result = { status: 'rejected', detail: 'wrong_session_or_busy' };
        else if (!['start','steer'].includes(command.mode)) result = {status:'rejected',detail:'unsupported_mode'};
        else {
            sending = true;
            try {
                const answer = await sendDesktopMessage({ sessionId: state.sessionId, text: command.text, mode: command.mode,
                    project: state.project, readState:true,
                    remoteSkillPath: command.interactionEnabled ? join(dirname(fileURLToPath(import.meta.url)),'../skills/remote-interaction/SKILL.md') : undefined,
                    onState:host => state.hostState(host) });
                result = {
                    status: answer.status === 'failed' ? 'rejected' : answer.status,
                    detail: answer.error || '',
                    ...(answer.turnId ? {turnId: answer.turnId, runId: digest(answer.turnId)} : {}),
                };
                if (answer.error === 'owner_unavailable') { client.event('session.removed', {sessionId:state.sessionId}); }
            } catch { result = {status:'unknown',detail:'delivery_result_unknown'}; } finally { sending = false; }
        }
        client.event('command.result', { requestId: command.requestId, ...result });
        if (retiring && !sending) stop();
    });
    let probing = false, stopped = false;
    const probe = async () => {
        if (probing || stopped) return;
        probing = true;
        try {
            const result = await sendDesktopMessage({sessionId:state.sessionId, probeOnly:true, readState:true});
            if (!stopped) state.ownerResult(result);
        } finally { probing = false; }
    };
    client.on('connected', async () => {
        state.ownerVerified = false;
        state.ownerUnavailable = false;
        state.currentSnapshot();
        try {
            const saved = await client.request('session.status', {sessionId:state.sessionId});
            state.restoreRuns(saved.runs);
        } catch { /* The first snapshot may not yet have created the row. */ }
        void probe();
    });
    let lease;
    const stop = async () => {
        if (stopped || sending || interactions.size) return;
        stopped = true;
        // A bridge response is a FIFO barrier: the preceding command.result has
        // reached the bridge before its connection is retired. Never replay it.
        if (retiring && client.ready) {
            try { await client.request('session.status',{sessionId:state.sessionId}); } catch { /* Delivery remains uncertain; never retry. */ }
        }
        clearInterval(lease);
        client.stop();
        server.close(async () => {
            try {
                if (replaceAfterStop) await launch(path, {event:'SessionStart',sessionId:state.sessionId,project:state.project,title:state.title}, replacementScript);
            } catch { /* A later status query reports the failed replacement as absent. */ }
            finally { process.exit(0); }
        });
    };
    const server = createServer(socket => {
        let buffer = '';
        socket.setEncoding('utf8');
        socket.setTimeout(6000, () => socket.destroy());
        socket.on('error', () => {});
        socket.on('data', chunk => {
            buffer += chunk.toString('utf8');
            if (Buffer.byteLength(buffer) > MAX) return socket.destroy();
            const index = buffer.indexOf('\n');
            if (index < 0) return;
            try {
                const data = JSON.parse(buffer.slice(0, index));
                if (data.sessionId !== initial.sessionId) throw new Error('Wrong session');
                if (data.event === 'Control') {
                    if (data.operation === 'identity') {
                        socket.end(JSON.stringify({protocol:1,build,currentVersion,sending:sending || interactions.size>0,retiring})+'\n');
                    } else if (data.operation === 'retire') {
                        void (async () => {
                        if (typeof data.script !== 'string' || !isAbsolute(data.script) || basename(data.script) !== 'hook.mjs' || basename(dirname(data.script)) !== 'codex') throw Error('Invalid replacement');
                        const manifest = JSON.parse(await readFile(join(dirname(data.script),'..','.codex-plugin','plugin.json'),'utf8'));
                        if (manifest.name !== 'polaris-agent') throw Error('Invalid replacement');
                        replacementScript = data.script;
                        retiring = true;
                        replaceAfterStop = true;
                        socket.end(JSON.stringify({protocol:1,build,currentVersion,status:sending || interactions.size?'deferred':'restarting'})+'\n', () => { if (!sending && !interactions.size) stop(); });
                        })().catch(()=>socket.end(JSON.stringify({error:'Invalid replacement'})+'\n'));
                    } else socket.end(JSON.stringify({error:'Unsupported control'})+'\n');
                } else if (data.event === 'Interaction') {
                    if (retiring || !client.ready) throw Error('Interaction unavailable');
                    socket.setTimeout(115000,()=>socket.destroy());
                    const controller=new AbortController();
                    interactions.add(controller);
                    socket.once('close',()=>controller.abort());
                    void waitForInteraction(client,state,data,controller.signal)
                        .then(result=>socket.end(JSON.stringify(result)+'\n'),()=>socket.end(JSON.stringify({error:'Interaction unavailable or expired'})+'\n'))
                        .finally(()=>{ interactions.delete(controller); if (retiring) void stop(); });
                } else if (data.event === 'Mark') {
                    void (async () => {
                        if (!client.ready) await new Promise((resolve,reject) => {
                            const ready=()=>{clearTimeout(timer);resolve();};
                            const timer=setTimeout(()=>{client.off('connected',ready);reject(Error('Polaris Agent is disconnected'));},4500);
                            client.once('connected',ready);
                        });
                        if (data.name) state.title = data.name;
                        state.snapshot();
                        return client.request('session.mark', {sessionId:state.sessionId});
                    })().then(result=>socket.end(JSON.stringify({result})+'\n'), error=>socket.end(JSON.stringify({error:error.message})+'\n'));
                } else {
                    if (data.event==='Interrupt' || data.event==='SessionEnd' ||
                        (data.event==='UserPromptSubmit' && data.turn && data.turn!==state.runId))
                        for (const controller of interactions) controller.abort();
                    const keep = state.handle(data);
                    socket.end('{}\n');
                    if (!keep) { for (const controller of interactions) controller.abort(); retiring = true; replaceAfterStop = false; void stop(); }
                }
            } catch { socket.destroy(); }
            buffer = '';
        });
    });
    server.on('error', error => {
        if (error.code === 'EADDRINUSE') process.send?.('existing');
        else process.send?.('failed');
        process.disconnect?.();
        client.stop();
        setTimeout(() => process.exit(0), 50);
    });
    server.listen(path, () => {
        // Keep checking an absent owner so reopening the chat recovers automatically.
        // Probe only this session; idle duration never expires a responsive owner.
        lease = setInterval(() => { void probe(); }, 15000);
        client.start();
        process.send?.('ready');
        process.disconnect?.();
    });
}

async function launch(path, initial, script = fileURLToPath(import.meta.url)) {
    return await new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [script, '--daemon'], {
            detached:true, windowsHide:true, stdio:['ignore','ignore','ignore','ipc'],
        });
        let settled = false;
        const finish = (error, result) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            child.unref();
            if (error) reject(error); else resolve(result);
        };
        const timer = setTimeout(() => {
            child.disconnect?.();
            finish(Error('Helper startup timeout'));
        }, 5000);
        child.on('error', error => finish(error));
        child.once('exit', () => finish(Error('Helper exited before ready')));
        child.once('message', message => {
            if (message !== 'ready' && message !== 'existing') return finish(Error('Helper unavailable'));
            forward(path, initial).then(result=>finish(null,result),finish);
        });
        child.send(initial, error => { if (error) finish(error); });
    });
}

try {
    if (controlMode) {
        let raw='';
        for await (const chunk of process.stdin) { raw += chunk; if (Buffer.byteLength(raw)>MAX) throw Error('Control input too large'); }
        const input=JSON.parse(raw), results=[];
        for (const entry of input.sessions || []) {
            const initial=metadata({hook_event_name:'SessionStart',session_id:entry.sessionId,cwd:entry.project});
            try {
                const path=await address(initial.sessionId,{create:false});
                const identity=await forward(path,{event:'Control',operation:'identity',project:initial.project,sessionId:initial.sessionId});
                if (identity?.protocol===1 && identity.retiring) results.push({sessionId:initial.sessionId,status:identity.sending?'deferred':'restarting',build:identity.build,currentVersion:identity.currentVersion});
                else if (identity?.protocol===1 && identity.build===build) results.push({sessionId:initial.sessionId,status:'current',build,currentVersion});
                else if (identity?.protocol===1 && statusOnly) results.push({sessionId:initial.sessionId,status:'update_available',build:identity.build,currentVersion:identity.currentVersion});
                else if (identity?.protocol===1) results.push({sessionId:initial.sessionId,...await forward(path,{event:'Control',operation:'retire',script:fileURLToPath(import.meta.url),sessionId:initial.sessionId})});
                else results.push({sessionId:initial.sessionId,status:'legacy_requires_restart'});
            } catch (error) {
                if (!['ENOENT','ECONNREFUSED'].includes(error.code)) {
                    results.push({sessionId:initial.sessionId,status:'unavailable'});
                    continue;
                }
                results.push({sessionId:initial.sessionId,status:'not_running'});
            }
        }
        process.stdout.write(JSON.stringify({build,currentVersion,results})+'\n');
    } else if (daemon) {
        process.once('message', initial => { void address(initial.sessionId).then(path => start(path, initial)).catch(() => process.exit(0)); });
    } else {
        let raw = '';
        process.stdin.setEncoding('utf8');
        for await (const chunk of (process.argv[2] === '--mark' ? [] : process.stdin)) {
            raw += chunk;
            // Only selected metadata and a bounded Stop reply are forwarded; prompts are discarded.
            if (Buffer.byteLength(raw) > 4 * 1024 * 1024) throw new Error('Hook too large');
        }
        let data;
        if (process.argv[2] === '--mark') {
            data={event:'Mark',sessionId:process.env.CODEX_THREAD_ID,project:process.cwd(),name:process.argv.slice(3).join(' ').slice(0,256)};
        } else if (process.argv[2] === '--ask') {
            const input=JSON.parse(raw);
            data={event:'Interaction',kind:'question',sessionId:process.env.CODEX_THREAD_ID,project:process.cwd(),prompt:input.question,options:input.options || []};
        } else {
            const input=JSON.parse(raw);
            data=input.hook_event_name==='PermissionRequest'
                ? {event:'Interaction',kind:'approval',sessionId:input.session_id,project:input.cwd,runId:digest(input.turn_id),prompt:permissionPrompt(input)}
                : metadata(input);
        }
        if (typeof data.sessionId !== 'string' || !data.sessionId.trim() || data.sessionId.length > 256) throw Error('Current CODEX_THREAD_ID is unavailable');
        const path = await address(data.sessionId);
        try {
            const reply = await forward(path, data);
            if(data.event==='Mark') process.stderr.write(JSON.stringify(reply)+'\n');
            if(data.event==='Interaction') {
                if(data.kind==='approval' && ['allow','deny'].includes(reply?.answer))
                    hookOutput={hookSpecificOutput:{hookEventName:'PermissionRequest',decision:{behavior:reply.answer}}};
                else if(data.kind==='question') {
                    if(typeof reply?.answer!=='string' || !reply.answer) throw Error('Question was not answered');
                    hookOutput={answer:reply.answer};
                }
            }
        } catch (error) {
            // Only a definite absence permits launch. Unknown delivery is never replayed.
            if (!['ENOENT','ECONNREFUSED'].includes(error.code) ||
                !['SessionStart', 'UserPromptSubmit', 'Mark'].includes(data.event)) throw error;
            const reply = await launch(path, data);
            if(data.event==='Mark') process.stderr.write(JSON.stringify(reply)+'\n');
        }

    }
} catch (error) {
    // Never include hook bodies, paths or credentials in host diagnostics.
    if(process.argv[2]==='--ask') {hookOutput={error:'Remote question unavailable or expired'};process.exitCode=1;}
    if(controlMode) {process.stderr.write('Helper upgrade failed\n');process.exitCode=1;}
    if(process.argv[2]==='--mark') {process.stderr.write(`Polaris mark failed: ${error.message}\n`);process.exitCode=1;}
} finally {
    if (!daemon && !controlMode) { process.stdout.write(JSON.stringify(hookOutput)+'\n'); if(!['--mark','--ask'].includes(process.argv[2])) process.exitCode = 0; }
}
