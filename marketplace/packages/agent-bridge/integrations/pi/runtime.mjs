import { randomUUID } from 'node:crypto';
import { basename } from 'node:path';
import { BridgeClient } from '../client.mjs';

const END = 'polaris.bridge.run-ended';
const NAME = 'polaris.bridge.name';
const text = message => typeof message.content === 'string' ? message.content
    : message.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
const isReply = entry => entry?.type === 'message' && entry.message.role === 'assistant'
    && ['stop', 'length'].includes(entry.message.stopReason)
    && !entry.message.content.some(part => part.type === 'toolCall');

// Read the raw active branch, not Pi's compacted model context. Only end markers
// are ours; message bodies and entry identities remain owned by Pi.
export function historyPage(manager, cursor = null, limit = 50, active = null) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw Error('invalid_history_limit');
    const current = manager.getBranch();
    let leafId = current.at(-1)?.id ?? null, afterId = null;
    if (cursor !== null) {
        let decoded;
        try { decoded = JSON.parse(Buffer.from(cursor, 'base64url').toString()); }
        catch { throw Error('invalid_history_cursor'); }
        if (typeof decoded.leafId !== 'string' || typeof decoded.afterId !== 'string') throw Error('invalid_history_cursor');
        ({leafId, afterId} = decoded);
        if (!current.some(entry => entry.id === leafId)) throw Error('history_branch_changed');
    }
    const branch = leafId === null ? [] : manager.getBranch(leafId);
    const positions = new Map(branch.map((entry, i) => [entry.id, i]));
    const covered = new Set(), runs = new Map(), replies = new Map();
    const cover = (run, end) => {
        const start = run.startEntryId === null ? -1 : positions.get(run.startEntryId);
        if (start === undefined) return;
        for (let i = start + 1; i <= end; i++) {
            covered.add(branch[i].id);
            if (branch[i].type === 'message' && branch[i].message.role === 'user') runs.set(branch[i].id, run.runId);
        }
    };
    branch.forEach((entry, i) => {
        if (entry.type !== 'custom' || entry.customType !== END) return;
        cover(entry.data, i);
        if (entry.data.finalEntryId) replies.set(entry.data.finalEntryId, entry.data);
    });
    if (active?.started) cover(active, branch.length - 1);
    const records = [];
    let candidate;
    const addReply = (entry, run) => records.push({id: entry.id, kind: 'reply', timestamp: entry.timestamp,
        text: text(entry.message), runId: run?.runId ?? null, status: run?.status ?? 'unknown',
        finality: run ? 'confirmed' : 'unknown', replyTruncated: entry.message.stopReason === 'length'});
    const flush = () => {
        // Old logs do not contain settlement boundaries. Expose only the last
        // terminal candidate between inputs, explicitly NOT as a confirmed end.
        if (isReply(candidate)) addReply(candidate, null);
        candidate = undefined;
    };
    for (const entry of branch) {
        if (entry.type !== 'message') continue;
        if (entry.message.role === 'user') {
            flush();
            records.push({id: entry.id, kind: 'input', timestamp: entry.timestamp,
                text: text(entry.message), runId: runs.get(entry.id) ?? null});
        } else if (entry.message.role === 'assistant') {
            if (covered.has(entry.id)) {
                flush();
                const run = replies.get(entry.id);
                if (run && isReply(entry)) addReply(entry, run);
            } else candidate = entry;
        }
    }
    flush();
    records.sort((a, b) => positions.get(a.id) - positions.get(b.id));
    const after = afterId === null ? -1 : records.findIndex(record => record.id === afterId);
    if (afterId !== null && after === -1) throw Error('invalid_history_cursor');
    const items = [];
    let bytes = 0;
    for (const record of records.slice(after + 1)) {
        const size = Buffer.byteLength(JSON.stringify(record));
        if (size > 768 * 1024) throw Error('history_entry_exceeds_bridge_frame');
        if (items.length === limit || bytes + size > 768 * 1024) break;
        items.push(record);
        bytes += size;
    }
    const more = after + 1 + items.length < records.length;
    const nextCursor = more ? Buffer.from(JSON.stringify({leafId, afterId: items.at(-1).id})).toString('base64url') : null;
    return {items, nextCursor, leafId};
}

export function install(pi, markSchema, Client = BridgeClient) {
    let context, client, sessionId, alias, active;
    let generation = 0, lastError = '';
    const report = error => {
        lastError = error.message;
        console.error(`[Agent Bridge] ${error.message}`);
        if (context?.hasUI) context.ui.setStatus('polaris-bridge', `Bridge: ${lastError}`);
    };
    const observe = (name, handler) => pi.on(name, (...args) => {
        try { handler(...args); } catch (error) { report(error); }
    });
    const snapshot = () => client?.event('session.snapshot', {
        sessionId, title: alias || context.sessionManager.getSessionName() || basename(context.cwd) || 'Pi',
        cwd: context.cwd, canSend: true, canReadHistory: true, liveness: 'host',
    });
    const begin = () => {
        if (!active) active = {runId: randomUUID(), startEntryId: context.sessionManager.getLeafId(),
            started: false, inputIds: new Set(), outcome: 'unknown'};
        return active;
    };
    const inputs = () => {
        if (!active?.started) return;
        const branch = context.sessionManager.getBranch();
        const start = active.startEntryId === null ? -1 : branch.findIndex(entry => entry.id === active.startEntryId);
        for (const entry of branch.slice(start + 1)) {
            if (entry.type !== 'message' || entry.message.role !== 'user' || active.inputIds.has(entry.id)) continue;
            if (client.event('run.input', {sessionId, runId: active.runId, id: entry.id,
                text: text(entry.message), timestamp: entry.timestamp})) active.inputIds.add(entry.id);
        }
    };
    const ending = (run, branch) => {
        const entry = branch.find(entry => entry.id === run.finalEntryId);
        const reply = entry ? text(entry.message) : null;
        return {sessionId, runId: run.runId, status: run.status,
            reply: reply === null ? null : Array.from(reply).slice(0, 128000).join(''),
            replyTruncated: entry?.message.stopReason === 'length' || (reply !== null && Array.from(reply).length > 128000)};
    };
    const close = () => {
        generation++;
        if (client) {
            client.event('session.removed', {sessionId});
            client.stop();
        }
        client = context = sessionId = alias = active = undefined;
    };
    observe('session_start', (_event, ctx) => {
        close();
        context = ctx;
        sessionId = ctx.sessionManager.getSessionId();
        alias = ctx.sessionManager.getBranch().findLast(entry => entry.type === 'custom' && entry.customType === NAME)?.data.name;
        const bound = sessionId, version = generation;
        client = new Client({adapter: 'pi', clientId: bound});
        client.on('protocol_error', report);
        client.on('connected', () => {
            try {
                snapshot();
                lastError = '';
                if (active?.started) {
                    client.event('run.started', {sessionId, runId: active.runId});
                    active.inputIds.clear();
                    inputs();
                } else {
                    const branch = context.sessionManager.getBranch();
                    const last = branch.findLast(entry => entry.type === 'custom' && entry.customType === END);
                    if (last) client.event('run.ended', ending(last.data, branch));
                }
            } catch (error) { report(error); }
        });
        const seen = new Set();
        client.on('command', command => {
            if (!['session.send', 'session.history'].includes(command.command)) return;
            const valid = () => version === generation && context && command.sessionId === bound
                && context.sessionManager.getSessionId() === bound;
            if (command.command === 'session.history') {
                try {
                    if (!valid()) throw Error('session_changed');
                    client.event('history.result', {sessionId, requestId: command.requestId,
                        result: historyPage(context.sessionManager, command.cursor, command.limit, active)});
                } catch (error) {
                    client?.event('history.result', {sessionId: bound, requestId: command.requestId, error: error.message});
                }
                return;
            }
            if (seen.has(command.requestId)) return;
            seen.add(command.requestId);
            const result = (status, detail, runId) => client?.event('command.result', {
                requestId: command.requestId, status, detail, ...(runId ? {runId} : {}),
            });
            try {
                if (!valid()) return result('rejected', 'session_changed');
                if (typeof command.text !== 'string' || !command.text.trim()) return result('rejected', 'invalid_text');
                if (!['start', 'steer'].includes(command.mode)) return result('rejected', 'unsupported_mode');
                if (command.mode === 'start' && !context.isIdle()) return result('rejected', 'session_busy');
                if (command.mode === 'steer' && context.isIdle()) return result('rejected', 'session_idle');
                if (command.mode === 'start') active = undefined;
                const run = begin();
                pi.sendUserMessage(command.text, command.mode === 'start'
                    ? {expandPromptTemplates: false} : {deliverAs: 'steer', expandPromptTemplates: false});
                // ExtensionAPI returns void: this acknowledges dispatch, not the
                // asynchronous preflight or execution. Only native events start a run.
                result('accepted', 'Accepted by Pi extension; execution is confirmed by run.started', run.runId);
            } catch (error) {
                if (!active?.started) active = undefined;
                report(error);
                result('unknown', 'Host dispatch failed; do not retry automatically');
            }
        });
        client.start();
    });
    observe('session_info_changed', () => { if (context) snapshot(); });
    observe('input', event => {
        if (!active || active.started) return;
        // A handled/failed asynchronous preflight has no agent_start. Never
        // attach a subsequent input to that abandoned delivery reservation.
        if (!active.inputObserved && event.source === 'extension') active.inputObserved = true;
        else active = undefined;
    });
    observe('agent_start', () => {
        if (!context) return;
        const run = begin();
        if (!run.started) {
            run.started = true;
            client.event('run.started', {sessionId, runId: run.runId});
        }
    });
    // User messages are persisted after message_end handlers. At turn_start
    // their native IDs are available; turn_end/settled also capture steering.
    observe('turn_start', inputs);
    observe('turn_end', inputs);
    observe('agent_before_settle', event => { if (active) active.outcome = event.outcome; });
    observe('agent_settled', event => {
        if (!context || !active?.started) return;
        inputs();
        const branch = context.sessionManager.getBranch();
        const start = active.startEntryId === null ? -1 : branch.findIndex(entry => entry.id === active.startEntryId);
        const last = branch.slice(start + 1).findLast(entry => entry.type === 'message' && entry.message.role === 'assistant');
        const status = event.aborted ? 'stopped' : active.outcome === 'error' ? 'failed'
            : active.outcome === 'completed' ? 'completed' : 'unknown';
        const record = {runId: active.runId, startEntryId: active.startEntryId,
            finalEntryId: status === 'completed' && isReply(last) ? last.id : null, status};
        pi.appendEntry(END, record);
        snapshot();
        client.event('run.ended', ending(record, branch));
        active = undefined;
    });
    observe('session_shutdown', close);
    const mark = async name => {
        if (!context || context.sessionManager.getSessionId() !== sessionId) throw Error('Cannot locate the current Pi session');
        if (name) {
            pi.appendEntry(NAME, {name});
            alias = name;
        }
        snapshot();
        return client.request('session.mark', {sessionId});
    };
    pi.registerCommand('polaris', {
        description: 'Agent Bridge: status | mark [name] | unmark',
        handler: async (args, ctx) => {
            try {
                const match = /^mark(?:\s+([\s\S]+))?$/.exec(args.trim());
                if (match) {
                    await mark(match[1]);
                    ctx.ui.notify('当前对话已标记到 Agent Bridge', 'info');
                } else if (args.trim() === 'unmark') {
                    await client.request('session.unmark', {sessionId});
                    ctx.ui.notify('已取消标记当前对话', 'info');
                } else {
                    const error = lastError || client?.lastError;
                    ctx.ui.notify(`Agent Bridge Pi 0.3.1 · ${client?.ready ? '已连接' : '未连接'}\n会话：${sessionId}${error ? '\n错误：' + error : ''}`, 'info');
                }
            } catch (error) { ctx.ui.notify(error.message, 'error'); }
        },
    });
    pi.registerTool({
        name: 'mark_current', label: 'Mark current chat',
        description: 'Mark this current chat in Agent Bridge only when the user explicitly asks to mark it. Never call for lifecycle notifications.',
        parameters: markSchema,
        execute: async (_id, params) => ({content: [{type: 'text', text: JSON.stringify(await mark(params.name))}], details: {}}),
    });
}
