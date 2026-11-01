// Short synchronous hook -> private local pipe -> persistent per-session bridge.
import { createConnection, createServer } from 'node:net';
import { mkdir, lstat } from 'node:fs/promises';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { BridgeClient } from '../client.mjs';
import { digest, metadata, Session } from './session.mjs';
import { sendDesktopMessage, sendModes } from './desktop-ipc.mjs';

const MAX = 65536;
const daemon = process.argv[2] === '--daemon';
if (!daemon) setTimeout(() => process.exit(process.argv[2]==='--mark'?1:0), process.argv[2]==='--mark'?7000:2200).unref();

async function address(sessionId) {
    const base = process.platform === 'win32' ? process.env.LOCALAPPDATA : (process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'));
    const root = process.env.POLARIS_AGENT_CODEX_DATA || join(base, 'polaris-agent', 'codex-hosts');
    await mkdir(root, { recursive: true, mode: 0o700 });
    const info = await lstat(root);
    if (!info.isDirectory() || info.isSymbolicLink() || (process.platform !== 'win32' &&
        (info.uid !== process.getuid() || (info.mode & 0o077)))) throw new Error('Private plugin data required');
    const key = digest(root + sessionId).slice(0, 40);
    return process.platform === 'win32' ? `\\\\.\\pipe\\polaris-codex-${key}` : join(root, `c-${key}.sock`);
}

async function forward(path, data) {
    return await new Promise((resolve, reject) => {
        const socket = createConnection(path);
        socket.setTimeout(data.event==='Mark'?6000:700, () => socket.destroy(new Error('Hook delivery timeout')));
        socket.on('error', reject);
        socket.on('connect', () => socket.write(JSON.stringify(data) + '\n'));
        socket.on('data', chunk => { socket.end(); try { const reply=JSON.parse(chunk.toString()); reply.error ? reject(Error(reply.error)) : resolve(reply); } catch {reject(Error('Invalid helper response'));} });
        socket.on('end', resolve);
    });
}

async function start(path, initial) {
    const client = new BridgeClient({ adapter: 'codex', clientId: initial.sessionId });
    const state = new Session(client, initial);
    state.sendModes = sendModes;
    const deliveries = new Set();
    let sending = false;
    client.on('command', async command => {
        if (command.command !== 'session.send' || deliveries.has(command.requestId)) return;
        deliveries.add(command.requestId);
        let result;
        if (command.sessionId !== state.sessionId || sending) result = { status: 'rejected', detail: 'wrong_session_or_busy' };
        else if (!['start','steer'].includes(command.mode)) result = {status:'rejected',detail:'unsupported_mode'};
        else if (command.mode==='start' && state.runId) result = {status:'rejected',detail:'session_busy'};
        else if (command.mode==='steer' && !state.runId) result = {status:'rejected',detail:'session_idle'};
        else {
            sending = true;
            try {
                const answer = await sendDesktopMessage({ sessionId: state.sessionId, text: command.text, mode: command.mode, project: state.project });
                result = {
                    status: answer.status === 'failed' ? 'rejected' : answer.status,
                    detail: answer.error || '',
                    ...(answer.turnId ? {turnId: answer.turnId} : {}),
                };
                if (answer.error === 'owner_unavailable') { client.event('session.removed', {sessionId:state.sessionId}); }
            } finally { sending = false; }
        }
        client.event('command.result', { requestId: command.requestId, ...result });
    });
    const probe = async () => {
        if (process.platform !== 'linux') return;
        const result = await sendDesktopMessage({sessionId:state.sessionId, probeOnly:true});
        state.ownerVerified = result.status === 'available';
        state.currentSnapshot();
        if (result.error === 'owner_unavailable') {
            client.event('session.removed', {sessionId:state.sessionId});
            stop();
        }
    };
    client.on('connected', () => {
        state.ownerVerified = false;
        state.currentSnapshot();
        void probe();
    });
    let lease;
    const stop = () => {
        clearInterval(lease);
        client.stop();
        server.close();
        setTimeout(() => process.exit(0), 300).unref();
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
                if (data.event === 'Mark') {
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
                    const keep = state.handle(data);
                    socket.end('{}\n');
                    if (!keep) stop();
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
        // Probe only this session's owner. Idle duration never expires a live owner.
        if (process.platform === 'linux') lease = setInterval(() => { void probe(); }, 60000);
        client.start();
        process.send?.('ready');
        process.disconnect?.();
    });
}

try {
    if (daemon) {
        process.once('message', initial => { void address(initial.sessionId).then(path => start(path, initial)).catch(() => process.exit(0)); });
    } else {
        let raw = '';
        process.stdin.setEncoding('utf8');
        for await (const chunk of (process.argv[2] === '--mark' ? [] : process.stdin)) {
            raw += chunk;
            // Only selected metadata and a bounded Stop reply are forwarded; prompts are discarded.
            if (Buffer.byteLength(raw) > 4 * 1024 * 1024) throw new Error('Hook too large');
        }
        const data = process.argv[2] === '--mark' ? {
            event:'Mark', sessionId:process.env.CODEX_THREAD_ID, project:process.cwd(), name:process.argv.slice(3).join(' ').slice(0,256)
        } : metadata(JSON.parse(raw));
        if (typeof data.sessionId !== 'string' || !data.sessionId.trim() || data.sessionId.length > 256) throw Error('Current CODEX_THREAD_ID is unavailable');
        const path = await address(data.sessionId);
        try { const reply = await forward(path, data); if(data.event==='Mark') process.stderr.write(JSON.stringify(reply)+'\n'); }
        catch {
            // A late Stop after helper loss must not recreate a run or replay an ending.
            if (!['SessionStart', 'UserPromptSubmit', 'Mark'].includes(data.event)) throw new Error('No active helper');
            const reply = await new Promise((resolve, reject) => {
                const child = spawn(process.execPath, [fileURLToPath(import.meta.url), '--daemon'], {
                    detached: true, windowsHide: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
                });
                child.on('error', reject);
                child.once('message', message => {
                    child.unref();
                    if (message === 'failed') reject(new Error('Helper unavailable'));
                    else forward(path, data).then(resolve, reject);
                });
                child.send(data);
            });
            if(data.event==='Mark') process.stderr.write(JSON.stringify(reply)+'\n');
        }
    }
} catch (error) {
    // Never include hook bodies, paths or credentials in host diagnostics.
    if(process.argv[2]==='--mark') {process.stderr.write(`Polaris mark failed: ${error.message}\n`);process.exitCode=1;}
} finally {
    if (!daemon) { process.stdout.write('{}\n'); if(process.argv[2]!=='--mark') process.exitCode = 0; }
}
