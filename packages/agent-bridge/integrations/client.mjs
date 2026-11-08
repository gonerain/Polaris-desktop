import { EventEmitter } from 'node:events';
import { readFile, lstat } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createConnection } from 'node:net';
import { randomUUID } from 'node:crypto';

export function defaultEndpoint() {
    const base = process.platform === 'win32' ? process.env.LOCALAPPDATA
        : (process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'));
    return process.env.POLARIS_AGENT_ENDPOINT || join(base, 'polaris-agent', 'bridge', 'endpoint.json');
}

export class BridgeClient extends EventEmitter {
    constructor({adapter, clientId, endpoint} = {}) {
        super();
        Object.assign(this, {adapter, clientId, endpoint});
        this.pending = new Map();
        this.ready = false;
        this.stopped = true;
    }
    start() {
        if (!this.stopped) return;
        this.stopped = false;
        void this.connect();
    }
    async connect() {
        if (this.stopped || this.socket || this.connecting) return;
        this.connecting = true;
        try {
            const path = this.endpoint || defaultEndpoint();
            const stat = await lstat(path);
            if (!stat.isFile() || stat.size > 8192 || (process.platform !== 'win32' &&
                (stat.uid !== process.getuid() || (stat.mode & 0o077)))) throw Error('Private endpoint required');
            const doc = JSON.parse(await readFile(path, 'utf8'));
            if (doc.version !== 1 || doc.host !== '127.0.0.1' || !Number.isInteger(doc.port) ||
                doc.port < 1 || doc.port > 65535 || typeof doc.token !== 'string' || doc.token.length < 32)
                throw Error('Invalid endpoint');
            if (this.stopped) return;
            const socket = createConnection({host: doc.host, port: doc.port});
            this.socket = socket;
            let buffer = '';
            const handshake = setTimeout(() => { if (!this.ready) socket.destroy(); }, 5000);
            handshake.unref?.();
            socket.setEncoding('utf8');
            socket.on('error', () => socket.destroy());
            socket.on('close', () => {
                clearTimeout(handshake);
                if (this.socket !== socket) return;
                this.socket = undefined;
                this.ready = false;
                for (const pending of this.pending.values()) {
                    clearTimeout(pending.timer);
                    pending.reject(Error('Connection lost; result unknown'));
                }
                this.pending.clear();
                this.schedule();
            });
            socket.on('connect', () => this.send({
                type: 'hello', token: doc.token, adapter: this.adapter, clientId: this.clientId,
            }));
            socket.on('data', chunk => {
                buffer += chunk;
                if (Buffer.byteLength(buffer) > 1048576) return socket.destroy();
                let index;
                while ((index = buffer.indexOf('\n')) >= 0) {
                    let frame;
                    try { frame = JSON.parse(buffer.slice(0, index)); }
                    catch { return socket.destroy(); }
                    buffer = buffer.slice(index + 1);
                    if (frame.type === 'hello' && frame.ok) {
                        clearTimeout(handshake);
                        this.ready = true;
                        this.emit('connected');
                    } else if (frame.type === 'command' && this.ready) this.emit('command', frame);
                    else if (frame.type === 'response') {
                        const pending = this.pending.get(frame.requestId);
                        if (!pending) continue;
                        this.pending.delete(frame.requestId);
                        clearTimeout(pending.timer);
                        if (frame.error) pending.reject(Error(frame.error));
                        else pending.resolve(frame.result);
                    }
                }
            });
        } catch { this.schedule(); }
        finally { this.connecting = false; }
    }
    schedule() {
        if (!this.stopped && !this.retry) this.retry = setTimeout(() => {
            this.retry = undefined;
            void this.connect();
        }, 2000);
        this.retry?.unref?.();
    }
    send(frame) {
        const data = JSON.stringify(frame) + '\n';
        if (!this.socket || Buffer.byteLength(data) > 1048576 || this.socket.writableLength > 2097152)
            throw Error('Bridge unavailable');
        this.socket.write(data);
    }
    event(event, data) {
        if (!this.ready) return false;
        try {
            this.send({type: 'event', event, ...data});
            return true;
        } catch {
            this.socket?.destroy();
            return false;
        }
    }
    request(operation, params = {}) {
        if (!this.ready) return Promise.reject(Error('Agent Bridge is disconnected'));
        const requestId = randomUUID();
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(requestId);
                reject(Error('Response timeout; result unknown'));
            }, 5000);
            this.pending.set(requestId, {resolve, reject, timer});
            try { this.send({type: 'request', requestId, operation, params}); }
            catch (error) {
                clearTimeout(timer);
                this.pending.delete(requestId);
                reject(error);
            }
        });
    }
    stop() {
        this.stopped = true;
        clearTimeout(this.retry);
        this.socket?.end();
        this.socket?.destroy();
        this.ready = false;
    }
}
