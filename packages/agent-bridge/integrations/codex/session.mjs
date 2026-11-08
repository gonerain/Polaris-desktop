// Select lifecycle metadata and the latest Stop reply; never read prompts or transcripts.
import { createHash } from 'node:crypto';
import { basename } from 'node:path';

export const digest = value => createHash('sha256').update(value).digest('hex');
const clip = (value, size) => Array.from(value).slice(0, size).join('');
const events = new Set(['SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd']);

export function metadata(input) {
    if (!events.has(input?.hook_event_name) || typeof input.session_id !== 'string' ||
        !input.session_id.trim() || input.session_id.length > 256) throw new Error('Invalid hook');
    const reply = input.hook_event_name === 'Stop' && typeof input.last_assistant_message === 'string'
        ? clip(input.last_assistant_message, 8000) : undefined;
    const result = {
        ...(reply !== undefined ? {reply, replyTruncated: reply.length < input.last_assistant_message.length} : {}),
        event: input.hook_event_name,
        sessionId: input.session_id,
        project: clip(typeof input.cwd === 'string' ? input.cwd : '', 4096),
        turn: typeof input.turn_id === 'string' && input.turn_id.trim() ? digest(input.turn_id) : '',
    };
    // Leave room for the bridge envelope even when JSON escapes control characters.
    while (typeof result.reply === 'string' && Buffer.byteLength(JSON.stringify(result), 'utf8') > 56000) {
        result.reply = clip(result.reply, Math.max(0, Array.from(result.reply).length - 512));
        result.replyTruncated = true;
    }
    return result;
}

export class Session {
    constructor(client, initial) {
        this.client = client;
        this.sessionId = initial.sessionId;
        this.project = initial.project;
        this.runId = '';
        this.finished = new Set();
        this.candidateTurn = '';
        this.lastEnding = '';
        this.knownRuns = new Map();
    }
    snapshot() {
        if (this.ownerUnavailable) {
            this.client.event('session.removed', {sessionId:this.sessionId});
            return;
        }
        this.client.event('session.snapshot', {
            sessionId: this.sessionId, title: this.title || clip(`Codex · ${basename(this.project.replaceAll('\\', '/')) || 'session'} · ${this.sessionId.slice(-6)}`, 128),
            cwd: this.project, canSend: this.ownerVerified === true && this.sendModes?.length > 0,
            liveness: this.ownerVerified === true ? 'host' : 'unverified',
        });
    }
    currentSnapshot() {
        this.snapshot();
        if (!this.ownerUnavailable && this.runId) this.client.event('run.started', {sessionId:this.sessionId, runId:this.runId});
    }
    ownerResult(result) {
        this.ownerVerified = result.status === 'available';
        this.ownerUnavailable = result.error === 'owner_unavailable';
        if (result.state) this.hostState(result.state);
        this.currentSnapshot();
    }
    restoreRuns(runs) {
        for (const run of (runs || []).slice(-100)) {
            if (!this.knownRuns.has(run.id)) this.knownRuns.set(run.id, run);
        }
    }
    hostState(state) {
        const latest = state.runs.at(-1);
        this.snapshot();
        for (const run of state.runs) {
            const id = digest(run.turnId), previous = this.knownRuns.get(id);
            if (!previous && run !== latest && id !== this.runId) continue;
            if (run.status === 'running') {
                this.client.event('run.started', {sessionId:this.sessionId,runId:id});
            } else if (previous?.status !== run.status || (!previous?.reply && run.reply)) {
                const reply = run.reply ?? previous?.reply;
                this.client.event('run.ended', {sessionId:this.sessionId,runId:id,status:run.status,
                    ...(typeof reply === 'string' ? {reply,replyTruncated:(run.reply !== undefined ? run.replyTruncated : previous?.replyTruncated) === true} : {})});
                this.finished.add(id);
            }
            this.knownRuns.set(id, {...previous,...run,id,status:run.status});
        }
        const active = state.runs.findLast(run => run.status === 'running');
        this.runId = active ? digest(active.turnId) : '';
        if (latest) this.candidateTurn = digest(latest.turnId);
        while (this.knownRuns.size > 100) this.knownRuns.delete(this.knownRuns.keys().next().value);
    }
    handle(data) {
        if (data.sessionId !== this.sessionId) throw new Error('Wrong session');
        this.project = data.project;
        if (data.event === 'SessionEnd') {
            this.client.event('session.removed', { sessionId: this.sessionId });
            return false;
        }
        if (data.event === 'UserPromptSubmit' && data.turn &&
            (!this.finished.has(data.turn) || data.turn === this.candidateTurn)) {
            if (data.turn !== this.candidateTurn) {
                this.candidateTurn = data.turn;
                this.lastEnding = '';
            }
            this.runId = data.turn;
            this.knownRuns.set(data.turn, {id:data.turn,status:'running'});
            this.snapshot();
            this.client.event('run.started', {sessionId: this.sessionId, runId: this.runId});
        } else if ((data.event === 'Stop' || data.event === 'Interrupt') && data.turn &&
            (data.turn === this.runId || (data.event === 'Stop' && data.turn === this.candidateTurn))) {
            const ending = {
                sessionId: this.sessionId, runId: data.turn,
                status: data.event === 'Interrupt' ? 'stopped' : 'unknown',
                ...(data.event === 'Stop' && typeof data.reply === 'string'
                    ? {reply: data.reply, replyTruncated: data.replyTruncated === true} : {}),
            };
            // Stop is only a candidate ending. A later Stop in the same turn may
            // contain a newer reply after another hook requested continuation.
            const fingerprint = JSON.stringify(ending);
            const previous = this.knownRuns.get(data.turn);
            if (!['completed','failed','stopped'].includes(previous?.status)) this.knownRuns.set(data.turn, {id:data.turn,...ending});
            if (fingerprint !== this.lastEnding) {
                this.client.event('run.ended', ending);
                this.lastEnding = fingerprint;
            }
            this.finished.add(data.turn);
            if (this.finished.size > 1024) this.finished.delete(this.finished.values().next().value);
            this.runId = '';
        } else {
            this.snapshot();
        }
        return true;
    }
}
