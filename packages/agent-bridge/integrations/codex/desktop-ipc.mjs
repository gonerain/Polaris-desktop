// Desktop-internal IPC. Windows uses the desktop's local named pipe;
// Unix uses its current-user socket. Sending remains enabled only where tested.
import { createConnection } from 'node:net';
import { lstat } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';

const MAX = 32 * 1024 * 1024;
export const sendModes = ['linux', 'win32'].includes(process.platform) ? ['start', 'steer'] : [];

export async function sendDesktopMessage({ sessionId, text, mode, project, socketPath, probeOnly = false, readState = false, onState, remoteSkillPath }) {
    let submitted = false, socket, timer, stateReply, ownerId, clientId = 'polaris';
    const pending = new Map();
    const failure = code => ({ status: submitted ? 'unknown' : 'failed', error: code });
    if (!probeOnly && !sendModes.includes(mode)) return failure('unsupported');
    if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 256 ||
        (!probeOnly && (typeof text !== 'string' || !text.trim() || text.length > 128000))) return failure('invalid_params');
    const path = socketPath || process.env.POLARIS_CODEX_IPC || (process.platform === 'win32' ? '\\\\.\\pipe\\codex-ipc'
        : join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'ipc', 'ipc.sock'));
    try {
        if (process.platform === 'win32') {
            // Never connect to a remote machine's pipe or interpret a file as IPC.
            const prefix = '\\\\.\\pipe\\';
            if (!path.startsWith(prefix) || !path.slice(prefix.length) || /[\\/]/.test(path.slice(prefix.length))) return failure('unsafe_endpoint');
        } else {
            const info = await lstat(path);
            if (!info.isSocket() || info.uid !== process.getuid() || (info.mode & 0o077)) return failure('unsafe_endpoint');
        }
        socket = createConnection(path);
        let buffer = Buffer.alloc(0);
        const failAll = () => {
            for (const { reject } of pending.values()) reject(new Error('transport'));
            pending.clear();
            stateReply?.reject(new Error('transport'));
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
                    if (message.type === 'broadcast' && message.method === 'thread-stream-state-changed' &&
                        message.version === 11 && message.sourceClientId === ownerId &&
                        message.params?.hostId === 'local' && message.params?.conversationId === sessionId &&
                        message.params?.change?.type === 'snapshot') {
                        stateReply?.resolve(message.params.change.conversationState);
                    }
                    if (message.type !== 'response') continue;
                    const entry = pending.get(message.requestId);
                    if (entry) { pending.delete(message.requestId); entry.resolve(message); }
                } catch { socket.destroy(); return; }
            }
        });
        const follow = following => {
            const body = Buffer.from(JSON.stringify({type:'broadcast', sourceClientId:clientId,
                method:'thread-stream-following-changed', version:1, targetClientIds:[ownerId],
                params:{hostId:'local',conversationId:sessionId,following}}));
            const header = Buffer.alloc(4); header.writeUInt32LE(body.length);
            socket.write(Buffer.concat([header,body]));
        };
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
            if (owner.resultType !== 'success') return failure(owner.error === 'no-client-found' ? 'owner_unavailable' : 'owner_probe_unknown');
            if (!owner.handledByClientId) return failure('owner_unavailable');
            ownerId = owner.handledByClientId;
            let state;
            if (readState) {
                const snapshot = new Promise((resolve,reject) => { stateReply = {resolve,reject}; });
                follow(true);
                try { state = selectRunState(await snapshot); }
                finally { follow(false); stateReply = undefined; }
                if (!state) return failure('state_unavailable');
                onState?.(state);
            }
            if (probeOnly) return { status: 'available', ...(state ? {state} : {}) };
            if (state && mode === 'start' && state.busy) return failure('session_busy');
            if (state && mode === 'steer' && !state.busy) return failure('session_idle');
            const clientUserMessageId = randomUUID();
            const input = [{ type: 'text', text, text_elements: [] }];
            if (remoteSkillPath) {
                if (typeof remoteSkillPath!=='string' || !isAbsolute(remoteSkillPath)) return failure('invalid_skill_path');
                input.push({type:'skill',name:'remote-interaction',path:remoteSkillPath});
            }
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

// Discard prompts, tool outputs and other conversation contents immediately.
// Retain bounded run metadata and final replies; never prompts or tool outputs.
export function selectRunState(conversation) {
    if (!conversation || typeof conversation !== 'object') return null;
    let turns = conversation.turns;
    if (conversation.turnHistory?.kind === 'canonical') {
        const history = conversation.turnHistory.history;
        if (!Array.isArray(history?.islands) || !history.entitiesByKey) return null;
        turns = history.islands.flatMap(island => (island.entries || []).map(entry => history.entitiesByKey[entry.value]));
    }
    if (!Array.isArray(turns) || turns.some(turn => !turn || typeof turn.status !== 'string')) return null;
    const statuses = {inProgress:'running',completed:'completed',failed:'failed',interrupted:'stopped'};
    if (turns.some(turn => !statuses[turn.status])) return null;
    const runs = turns.slice(-100).filter(turn => typeof turn.turnId === 'string' && turn.turnId).map(turn => {
        const final = turn.status !== 'inProgress' && Array.isArray(turn.items)
            ? turn.items.findLast(item => item.type === 'agentMessage' && item.phase === 'final_answer' && typeof item.text === 'string') : null;
        return {turnId:turn.turnId, status:statuses[turn.status],
            ...(final ? {reply:Array.from(final.text).slice(0,8000).join(''),replyTruncated:Array.from(final.text).length > 8000} : {})};
    });
    return {busy:turns.some(turn => turn.status === 'inProgress'), runs};
}
