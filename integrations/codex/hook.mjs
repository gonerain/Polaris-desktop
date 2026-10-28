// Short synchronous hook -> private local pipe -> persistent per-session bridge.
import { createConnection, createServer } from 'node:net';
import { mkdir, lstat } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { BridgeClient } from '../client.mjs';
import { digest, metadata, Session } from './session.mjs';

const MAX = 65536;
const daemon = process.argv[2] === '--daemon';
if (!daemon) setTimeout(() => process.exit(0), 2200).unref();

async function address(sessionId) {
    const root = process.env.PLUGIN_DATA || process.env.CLAUDE_PLUGIN_DATA;
    if (!root) throw new Error('Plugin data directory unavailable');
    await mkdir(root, { recursive: true, mode: 0o700 });
    const info = await lstat(root);
    if (!info.isDirectory() || info.isSymbolicLink() || (process.platform !== 'win32' &&
        (info.uid !== process.getuid() || (info.mode & 0o077)))) throw new Error('Private plugin data required');
    const key = digest(root + sessionId).slice(0, 40);
    return process.platform === 'win32' ? `\\\\.\\pipe\\polaris-codex-${key}` : join(root, `c-${key}.sock`);
}

async function forward(path, data) {
    await new Promise((resolve, reject) => {
        const socket = createConnection(path);
        socket.setTimeout(700, () => socket.destroy(new Error('Hook delivery timeout')));
        socket.on('error', reject);
        socket.on('connect', () => socket.write(JSON.stringify(data) + '\n'));
        socket.on('data', () => { socket.end(); resolve(); });
        socket.on('end', resolve);
    });
}

async function start(path, initial) {
    const relay = process.env.POLARIS_RELAY ? JSON.parse(process.env.POLARIS_RELAY) : undefined;
    const client = new BridgeClient({ name: 'Codex hooks', relay });
    const state = new Session(client, initial);
    client.on('connected', () => state.snapshot());
    let lease;
    const stop = () => {
        clearTimeout(lease);
        client.stop();
        server.close();
        setTimeout(() => process.exit(0), 300).unref();
    };
    const server = createServer(socket => {
        let buffer = '';
        socket.setEncoding('utf8');
        socket.setTimeout(1000, () => socket.destroy());
        socket.on('error', () => {});
        socket.on('data', chunk => {
            buffer += chunk.toString('utf8');
            if (Buffer.byteLength(buffer) > MAX) return socket.destroy();
            const index = buffer.indexOf('\n');
            if (index < 0) return;
            try {
                const data = JSON.parse(buffer.slice(0, index));
                if (data.sessionId !== initial.sessionId) throw new Error('Wrong session');
                clearTimeout(lease);
                // Bound abandoned helpers after Codex crashes; no session polling.
                lease = setTimeout(stop, 35 * 60000);
                const keep = state.handle(data);
                socket.end('{}\n');
                if (!keep) stop();
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
        lease = setTimeout(stop, 35 * 60000);
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
        for await (const chunk of process.stdin) {
            raw += chunk;
            // Hooks can contain a long prompt/reply, but it is never forwarded or saved.
            if (Buffer.byteLength(raw) > 4 * 1024 * 1024) throw new Error('Hook too large');
        }
        const data = metadata(JSON.parse(raw));
        const path = await address(data.sessionId);
        try { await forward(path, data); }
        catch {
            // A late Stop after helper loss must not recreate a run or replay an ending.
            if (!['SessionStart', 'UserPromptSubmit'].includes(data.event)) throw new Error('No active helper');
            await new Promise((resolve, reject) => {
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
        }
    }
} catch {
    // Hooks are advisory; failures must not block Codex or inject private diagnostics.
} finally {
    if (!daemon) { process.stdout.write('{}\n'); process.exitCode = 0; }
}
