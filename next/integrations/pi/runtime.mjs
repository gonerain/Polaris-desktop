import { randomUUID } from 'node:crypto';
import { basename } from 'node:path';
import { BridgeClient } from '../client.mjs';

export function install(pi, markSchema, Client = BridgeClient) {
    let context, client, sessionId, alias;
    let runId = '', lastStop = '', reply = '', generation = 0;
    const snapshot = () => client?.event('session.snapshot', {
        sessionId, title: alias || context.sessionManager.getSessionName() || basename(context.cwd) || 'Pi',
        cwd: context.cwd, canSend: true, liveness: 'host',
    });
    // Lifecycle telemetry must never interrupt Pi's own processing.
    const observe = (name, handler) => pi.on(name, (...args) => {
        try { handler(...args); } catch { /* Host continues if metadata is unavailable. */ }
    });
    const close = () => {
        generation++;
        if (client) {
            client.event('session.removed', {sessionId});
            client.stop();
        }
        client = context = sessionId = alias = undefined;
        runId = '';
    };
    observe('session_start', (_event, ctx) => {
        close();
        context = ctx;
        sessionId = ctx.sessionManager.getSessionId();
        const bound = sessionId, version = generation;
        client = new Client({adapter: 'pi', clientId: bound});
        client.on('connected', () => {
            try {
                snapshot();
                if (runId) client.event('run.started', {sessionId, runId});
            } catch { /* Reconnect only publishes available current state. */ }
        });
        const seen = new Set();
        client.on('command', command => {
            if (command.command !== 'session.send' || seen.has(command.requestId)) return;
            seen.add(command.requestId);
            const result = (status, detail, submittedRun) => client?.event('command.result', {
                requestId: command.requestId, status, detail, ...(submittedRun ? {runId:submittedRun} : {}),
            });
            try {
                if (version !== generation || !context || command.sessionId !== bound ||
                    context.sessionManager.getSessionId() !== bound) return result('rejected', 'session_changed');
                if (typeof command.text !== 'string' || !command.text.trim()) return result('rejected', 'invalid_text');
                if (!['start', 'steer'].includes(command.mode)) return result('rejected', 'unsupported_mode');
                if (command.mode === 'start' && !context.isIdle()) return result('rejected', 'session_busy');
                if (command.mode === 'steer' && context.isIdle()) return result('rejected', 'session_idle');
                if (command.mode === 'start') { runId = randomUUID(); reply = ''; lastStop = ''; }
                const submittedRun = runId;
                pi.sendUserMessage(command.text, command.mode === 'start'
                    ? {expandPromptTemplates: false} : {deliverAs: 'steer', expandPromptTemplates: false});
                result('accepted', 'Submitted to the bound Pi session', submittedRun);
            } catch { result('unknown', 'Host dispatch failed; do not retry automatically'); }
        });
        client.start();
    });
    observe('session_info_changed', () => { if (context) snapshot(); });
    observe('agent_start', () => {
        if (!context) return;
        if (!runId) { runId = randomUUID(); reply = ''; lastStop = ''; }
        client?.event('run.started', {sessionId, runId});
    });
    observe('message_end', event => {
        if (!runId || event.message?.role !== 'assistant') return;
        lastStop = event.message.stopReason;
        reply = event.message.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
    });
    observe('agent_settled', event => {
        if (!context || !runId) return;
        try {
            snapshot();
            client?.event('run.ended', {
                sessionId, runId,
                status: event.aborted || lastStop === 'aborted' ? 'stopped'
                    : lastStop === 'error' ? 'failed' : lastStop === 'stop' ? 'completed' : 'unknown',
                reply: Array.from(reply).slice(0, 128000).join(''),
                replyTruncated: Array.from(reply).length > 128000,
            });
        } finally { runId = ''; }
    });
    observe('session_shutdown', close);
    const mark = async name => {
        if (!context || context.sessionManager.getSessionId() !== sessionId) throw Error('Cannot locate the current Pi session');
        if (name) alias = name;
        snapshot();
        return client.request('session.mark', {sessionId});
    };
    pi.registerCommand('polaris', {
        description: 'Polaris Agent: mark [name] explicitly marks this chat',
        handler: async (args, ctx) => {
            try {
                const match = /^mark(?:\s+([\s\S]+))?$/.exec(args.trim());
                if (match) {
                    await mark(match[1]);
                    ctx.ui.notify('当前对话已标记到 Polaris Agent', 'info');
                } else ctx.ui.notify(client?.ready ? 'Polaris Agent 已连接；/polaris mark [名称] 标记当前对话' : 'Polaris Agent 未连接', 'info');
            } catch (error) { ctx.ui.notify(error.message, 'error'); }
        },
    });
    pi.registerTool({
        name: 'mark_current', label: 'Mark current chat',
        description: 'Mark this current chat in Polaris Agent only when the user explicitly asks to mark it. Never call for lifecycle notifications.',
        parameters: markSchema,
        execute: async (_id, params) => ({content: [{type: 'text', text: JSON.stringify(await mark(params.name))}], details: {}}),
    });
}
