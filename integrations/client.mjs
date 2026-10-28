// Provider-neutral Node client. No Pi imports, TCP, shell commands or offline queue.
import { EventEmitter } from "node:events";
import { readFile, lstat } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createConnection } from "node:net";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";

const MAX_FRAME = 65536;

export function defaultEndpoint() {
    if (process.env.POLARIS_ENDPOINT) return process.env.POLARIS_ENDPOINT;
    const base = process.platform === "win32"
        ? process.env.LOCALAPPDATA
        : (process.env.XDG_DATA_HOME || join(homedir(), ".local", "share"));
    if (!base) throw new Error("Cannot determine Polaris user data directory");
    return join(base, "Polaris", "Polaris", "bridge", "endpoint.json");
}

export class BridgeClient extends EventEmitter {
    constructor({ name, instanceId = randomUUID(), endpoint, relay } = {}) {
        super();
        this.name = name || "Agent";
        this.instanceId = instanceId;
        this.endpoint = endpoint;
        // Explicit argv array: e.g. ["/mnt/d/.../Polaris.exe", "--bridge-stdio"].
        this.relay = relay;
        this.ready = false;
        this.pending = new Map();
        this.stopped = true;
        this.retryDelay = 1000;
        this.buffer = Buffer.alloc(0);
        this.generation = 0;
    }

    start() {
        if (!this.stopped) return;
        this.stopped = false;
        void this.connect();
    }

    async connect() {
        if (this.stopped || this.connecting || this.stream) return;
        this.connecting = true;
        const generation = ++this.generation;
        const disconnected = reason => { if (generation === this.generation) this.disconnected(reason); };
        const receive = data => { if (generation === this.generation) this.receive(data); };
        try {
            let token = "";
            if (this.relay) {
                if (!Array.isArray(this.relay) || !this.relay.length || this.relay.some(x => typeof x !== "string"))
                    throw new Error("POLARIS_RELAY must be a JSON argv array");
                const child = spawn(this.relay[0], this.relay.slice(1), { stdio: ["pipe", "pipe", "pipe"], windowsHide: true, shell: false });
                this.child = child;
                this.stream = child.stdin;
                child.stdout.on("data", receive);
                child.stderr.resume(); // Never forward credentials or helper noise into a model context.
                child.on("error", error => disconnected(error.message));
                child.on("exit", () => disconnected("Polaris relay disconnected"));
                child.stdin.on("error", error => disconnected(error.message));
            } else {
                const path = this.endpoint || defaultEndpoint();
                const info = await lstat(path);
                if (info.size > 8192 || !info.isFile() || (process.platform !== "win32" &&
                    (info.uid !== process.getuid() || (info.mode & 0o077))))
                    throw new Error("Polaris endpoint must be a private file owned by this user");
                const document = JSON.parse(await readFile(path, "utf8"));
                if (this.stopped || generation !== this.generation) return;
                if (document.protocol !== 1 || typeof document.address !== "string" ||
                    !/^[0-9a-f]{64}$/.test(document.token)) throw new Error("Invalid Polaris endpoint");
                if (document.address.includes("\0") || (process.platform === "win32"
                    ? !document.address.startsWith("\\\\.\\pipe\\") : !document.address.startsWith("/")))
                    throw new Error("Endpoint must be a local pipe or Unix socket");
                token = document.token;
                const socket = createConnection(document.address);
                this.stream = socket;
                socket.on("data", receive);
                socket.on("error", error => disconnected(error.message));
                socket.on("close", () => disconnected("Polaris disconnected"));
            }
            this.buffer = Buffer.alloc(0);
            await this.request("hello", { protocol: 1, token, instanceId: this.instanceId, name: this.name }, true);
            if (this.stopped || !this.stream || generation !== this.generation) return;
            this.ready = true;
            this.lastError = "";
            this.retryDelay = 1000;
            this.heartbeat = setInterval(() => {
                void this.request("heartbeat", {}).catch(() => this.disconnected("Heartbeat failed"));
            }, 15000);
            this.heartbeat.unref?.();
            this.emit("connected");
        } catch (error) {
            disconnected(error instanceof Error ? error.message : "Connection failed");
        } finally {
            this.connecting = false;
        }
    }

    receive(chunk) {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        if (this.buffer.length > MAX_FRAME * 2) return this.disconnected("Oversized response");
        let index;
        while ((index = this.buffer.indexOf(10)) >= 0) {
            if (index + 1 > MAX_FRAME) return this.disconnected("Oversized response");
            const line = this.buffer.subarray(0, index).toString("utf8");
            this.buffer = this.buffer.subarray(index + 1);
            try {
                const response = JSON.parse(line);
                const pending = this.pending.get(response.id);
                if (!pending) continue;
                this.pending.delete(response.id);
                clearTimeout(pending.timer);
                if (response.ok === true) pending.resolve(response.result);
                else pending.reject(new Error(`${response.error?.code || "error"}: ${response.error?.message || "Operation failed"}`));
            } catch {
                return this.disconnected("Invalid JSON response");
            }
        }
        if (this.buffer.length > MAX_FRAME) this.disconnected("Oversized response");
    }

    send(message) {
        if (!this.stream || this.stream.destroyed) throw new Error("Polaris is not connected");
        const frame = Buffer.from(JSON.stringify(message) + "\n", "utf8");
        if (frame.length > MAX_FRAME || this.stream.writableLength + frame.length > MAX_FRAME * 2)
            throw new Error("Polaris message/backlog exceeds limit");
        this.stream.write(frame);
    }

    request(method, params = {}, handshake = false) {
        if ((!this.ready && !handshake) || this.pending.size >= 32)
            return Promise.reject(new Error("Polaris 未连接，或请求过多；请先打开 Polaris"));
        const id = randomUUID();
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error("Polaris 响应超时，操作结果未知；先查询，不要自动重试修改"));
            }, 15000);
            this.pending.set(id, { resolve, reject, timer, method });
            try { this.send({ id, method, params }); }
            catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
        });
    }

    event(event, data) {
        // No offline replay: reconnect publishes a fresh snapshot instead.
        if (!this.ready) return false;
        try { this.send({ event, data }); return true; }
        catch { this.disconnected("Cannot send event"); return false; }
    }

    disconnected(reason) {
        this.lastError = reason;
        this.generation += 1;
        const wasConnected = this.ready || this.stream;
        this.ready = false;
        clearInterval(this.heartbeat);
        const stream = this.stream;
        this.stream = undefined;
        stream?.destroy();
        const child = this.child;
        this.child = undefined;
        child?.kill();
        for (const item of this.pending.values()) {
            clearTimeout(item.timer);
            item.reject(new Error(item.method === "components.call"
                ? reason + "；操作可能已应用，先查询，勿自动重试修改" : reason));
        }
        this.pending.clear();
        if (wasConnected) this.emit("disconnected", reason);
        if (!this.stopped && !this.retry) {
            this.retry = setTimeout(() => { this.retry = undefined; void this.connect(); }, this.retryDelay);
            this.retryDelay = Math.min(this.retryDelay * 2, 10000);
        }
    }

    stop() {
        this.stopped = true;
        this.generation += 1;
        clearTimeout(this.retry);
        this.retry = undefined;
        clearInterval(this.heartbeat);
        // Flush a final session.removed event before closing the transport.
        const stream = this.stream, child = this.child;
        this.stream = undefined;
        this.child = undefined;
        stream?.end();
        const cleanup = setTimeout(() => { stream?.destroy(); child?.kill(); }, 250);
        cleanup.unref?.();
        this.ready = false;
        for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new Error("Adapter stopped")); }
        this.pending.clear();
    }
}
