// Desktop-internal IPC, verified with the Linux desktop bundled Codex 0.160.1.
import { createConnection } from 'node:net';
import { lstat } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

const MAX = 4 * 1024 * 1024;
export const sendModes = process.platform === 'linux' ? ['start', 'steer'] : [];

export async function sendDesktopMessage({ sessionId, text, mode, project, socketPath, probeOnly = false }) {
    let submitted = false, socket, timer;
    const pending = new Map();
    const failure = code => ({ status: submitted ? 'unknown' : 'failed', error: code });
    if (!probeOnly && !sendModes.includes(mode)) return failure('unsupported');
    if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 256 ||
        (!probeOnly && (typeof text !== 'string' || !text.trim() || text.length > 128000))) return failure('invalid_params');
    const path = socketPath || join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'ipc', 'ipc.sock');
    try {
        const info = await lstat(path);
        if (!info.isSocket() || info.uid !== process.getuid() || (info.mode & 0o077)) return failure('unsafe_endpoint');
        socket = createConnection(path);
        let buffer = Buffer.alloc(0);
        const failAll = () => {
            for (const { reject } of pending.values()) reject(new Error('transport'));
            pending.clear();
        };
        socket.on('error', failAll);
        socket.on('close', failAll);
        socket.on('data', chunk => {
            buffer = Buffer.concat([buffer, chunk]);
            if (buffer.length > MAX + 4) return socket.destroy();
            while (buffer.length >= 4) {
                const size = buffer.readUInt32LE(0);
                if (!size || size > MAX) return socket.destroy();
                if (buffer.length < size + 4) break;
                const frame = buffer.subarray(4, size + 4);
                buffer = buffer.subarray(size + 4);
                try {
                    const message = JSON.parse(frame.toString('utf8'));
                    if (message.type !== 'response') continue;
                    const entry = pending.get(message.requestId);
                    if (entry) { pending.delete(message.requestId); entry.resolve(message); }
                } catch { socket.destroy(); return; }
            }
        });
        let clientId = 'polaris';
        const request = (method, params, version, targetClientId) => new Promise((resolve, reject) => {
            const requestId = randomUUID();
            const body = Buffer.from(JSON.stringify({ type: 'request', requestId, sourceClientId: clientId,
                method, params, version, targetClientId, timeoutMs: 15000 }));
            const header = Buffer.alloc(4); header.writeUInt32LE(body.length);
            pending.set(requestId, { resolve, reject });
            socket.write(Buffer.concat([header, body]));
        });
        const exchange = async () => {
            const init = await request('initialize', { clientType: 'polaris' }, 0);
            if (init.resultType !== 'success' || !init.result?.clientId) return failure('initialize_failed');
            clientId = init.result.clientId;
            const owner = await request('thread-owner-discovery', { hostId: 'local', conversationId: sessionId }, 1);
            if (owner.resultType !== 'success') return failure('owner_probe_unknown');
            if (!owner.handledByClientId) return failure('owner_unavailable');
            if (probeOnly) return { status: 'available' };
            const clientUserMessageId = randomUUID();
            const input = [{ type: 'text', text, text_elements: [] }];
            let params, method, version;
            if (mode === 'steer') {
                method = 'thread-follower-steer-turn'; version = 1;
                params = { conversationId: sessionId, clientUserMessageId, input, attachments: [],
                    restoreMessage: { id: clientUserMessageId, text, cwd: project || '/', createdAt: Date.now(),
                        context: { prompt: text, workspaceRoots: [project || '/'], addedFiles: [],
                            fileAttachments: [], imageAttachments: [], ideContext: null } } };
            } else {
                method = 'thread-follower-start-turn'; version = 2;
                params = { conversationId: sessionId, turnStart: { request: { threadId: sessionId, input,
                    clientUserMessageId }, context: { inheritThreadSettings: true } } };
            }
            // After this point a missing response is uncertain; never retry or change mode.
            submitted = true;
            const reply = await request(method, params, version, owner.handledByClientId);
            if (reply.resultType !== 'success') {
                const noDispatch = ['no-client-found', 'request-version-mismatch', 'unsupported-method'].includes(reply.error);
                return { status: noDispatch ? 'failed' : 'unknown', error: noDispatch ? 'unavailable' : 'delivery_unknown' };
            }
            const result = reply.result?.result;
            const turnId = result?.turnId || result?.turn?.id;
            if (typeof turnId !== 'string' || !turnId || turnId.length > 128) return failure('invalid_response');
            return { status: 'accepted', turnId };
        };
        return await Promise.race([exchange(), new Promise(resolve => {
            timer = setTimeout(() => resolve(failure('timeout')), 20000);
        })]);
    } catch { return failure('transport'); }
    finally { clearTimeout(timer); socket?.destroy(); }
}
