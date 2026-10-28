// Hook metadata only. Never inspect prompt, assistant text, transcript or process lists.
import { createHash } from 'node:crypto';
import { basename } from 'node:path';

export const digest = value => createHash('sha256').update(value).digest('hex');
const clip = (value, size) => Array.from(value).slice(0, size).join('');
const events = new Set(['SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd']);

export function metadata(input) {
    if (!events.has(input?.hook_event_name) || typeof input.session_id !== 'string' ||
        !input.session_id.trim() || input.session_id.length > 8192) throw new Error('Invalid hook');
    return {
        event: input.hook_event_name,
        sessionId: 'codex:' + digest(input.session_id),
        project: clip(typeof input.cwd === 'string' ? input.cwd : '', 4096),
        turn: typeof input.turn_id === 'string' && input.turn_id.trim() ? digest(input.turn_id) : '',
    };
}

export class Session {
    constructor(client, initial) {
        this.client = client;
        this.sessionId = initial.sessionId;
        this.project = initial.project;
        this.runId = '';
        this.finished = new Set();
    }
    snapshot() {
        this.client.event('session.snapshot', {
            sessionId: this.sessionId, source: 'Codex',
            // Hooks don't expose the native chat title; don't derive it from private text.
            name: clip(`Codex · ${basename(this.project.replaceAll('\\', '/')) || 'session'} · ${this.sessionId.slice(-6)}`, 128),
            project: this.project, state: this.runId ? 'running' : 'idle', runId: this.runId,
        });
    }
    handle(data) {
        if (data.sessionId !== this.sessionId) throw new Error('Wrong session');
        this.project = data.project;
        if (data.event === 'SessionEnd') {
            this.client.event('session.removed', { sessionId: this.sessionId });
            return false;
        }
        if (data.event === 'UserPromptSubmit' && data.turn && !this.finished.has(data.turn)) {
            // Steering/recovery of the same active turn must not allocate a second run.
            this.runId = data.turn;
            this.snapshot();
            this.client.event('run.started', { sessionId: this.sessionId, runId: this.runId });
        } else if ((data.event === 'Stop' || data.event === 'Interrupt') && data.turn && data.turn === this.runId) {
            this.client.event('run.ended', { sessionId: this.sessionId, runId: this.runId,
                outcome: data.event === 'Interrupt' ? 'cancelled' : 'unknown' });
            this.finished.add(this.runId);
            if (this.finished.size > 1024) this.finished.delete(this.finished.values().next().value);
            this.runId = '';
        } else {
            this.snapshot();
        }
        return true;
    }
}
