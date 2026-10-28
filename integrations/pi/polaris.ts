import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createHash, randomUUID } from "node:crypto";
import { basename } from "node:path";
import { BridgeClient } from "../client.mjs";

/** Thin Pi adapter: lifecycle -> protocol. No calendar types or task-file access. */
export default function (pi: ExtensionAPI) {
    let client: BridgeClient | undefined;
    let context: ExtensionContext | undefined;
    let runId = "";
    let outcome = "";
    let lastStop: string | undefined;

    const sessionId = () => {
        const id = context!.sessionManager.getSessionId();
        return id.length <= 256 ? id : "sha256:" + createHash("sha256").update(id).digest("hex");
    };
    const truncate = (value: string, length: number) => Array.from(value).slice(0, length).join("");
    const snapshot = () => {
        if (!context || !client) return;
        client.event("session.snapshot", {
            sessionId: sessionId(), source: "Pi",
            name: truncate(context.sessionManager.getSessionName() || basename(context.cwd) || "Pi session", 128),
            project: truncate(context.cwd, 4096), state: runId ? "running" : "idle", runId, outcome,
        });
    };

    pi.on("session_start", (_event, ctx) => {
        context = ctx;
        runId = ctx.isIdle() ? "" : randomUUID();
        outcome = "";
        lastStop = undefined;
        let relay: string[] | undefined;
        try {
            if (process.env.POLARIS_RELAY) {
                relay = JSON.parse(process.env.POLARIS_RELAY);
                if (!Array.isArray(relay) || !relay.length || relay.some(x => typeof x !== "string")) throw new Error();
            }
        } catch {
            if (ctx.hasUI) ctx.ui.notify("POLARIS_RELAY 必须是 JSON 命令参数数组；未连接 Polaris", "error");
            return;
        }
        client = new BridgeClient({ name: "Pi", relay });
        client.on("connected", snapshot);
        client.start(); // Nonblocking: Polaris being absent must not delay Pi.
    });

    pi.on("session_info_changed", () => snapshot());
    pi.on("agent_start", () => {
        if (!context) return;
        // Retries / recovery may emit agent_start again before settlement.
        if (!runId) { runId = randomUUID(); lastStop = undefined; outcome = ""; }
        client?.event("run.started", { sessionId: sessionId(), runId });
    });
    pi.on("message_end", event => {
        if (runId && event.message.role === "assistant") lastStop = event.message.stopReason;
    });
    pi.on("agent_settled", event => {
        if (!context || !runId) return;
        snapshot(); // Refresh the native session title before reporting settlement.
        outcome = event.aborted || lastStop === "aborted" ? "cancelled"
            : lastStop === "error" ? "failed" : lastStop === "stop" ? "ended" : "unknown";
        client?.event("run.ended", { sessionId: sessionId(), runId, outcome });
        runId = "";
    });
    pi.on("session_shutdown", () => {
        if (context) client?.event("session.removed", { sessionId: sessionId() });
        client?.stop();
        client = undefined;
        context = undefined;
        runId = "";
    });

    pi.registerCommand("polaris", {
        description: "查看 Polaris 连接状态（connect 可重新尝试连接）",
        handler: async (args, ctx) => {
            if (args.trim() === "connect") void client?.connect();
            if (ctx.hasUI) ctx.ui.notify(client?.ready ? "Polaris 已连接；结束气泡自动触发，只有组件工具访问需要授权"
                : "Polaris 未连接：" + (client?.lastError || "正在连接，请稍后重试")
                  + "。请打开 Polaris，检查端点或 POLARIS_RELAY", "info");
        },
    });

    const invoke = async (method: string, params: Record<string, unknown>) => {
        if (!client) throw new Error("Polaris 插件尚未建立会话");
        const result = await client.request(method, params);
        return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result };
    };
    pi.registerTool({
        name: "polaris_components", label: "Polaris components",
        description: "发现 Polaris 明确开放的组件，仅返回名称和ID，不读取业务数据。",
        parameters: Type.Object({}),
        execute: async () => invoke("components.list", {}),
    });
    pi.registerTool({
        name: "polaris_help", label: "Polaris component help",
        description: "读取组件的操作、参数、权限和示例。调用组件前先查询 help；help 不授予数据访问权限。",
        parameters: Type.Object({ component: Type.String() }),
        execute: async (_id, params) => invoke("components.help", params),
    });
    pi.registerTool({
        name: "polaris_call", label: "Polaris component call",
        description: "按组件 help 调用操作。须由用户在 Polaris 授权；不自动读取所有组件。写入超时或 applied=true 时禁止盲目重试，先查询实际结果。",
        parameters: Type.Object({ component: Type.String(), operation: Type.String(),
            args: Type.Optional(Type.Record(Type.String(), Type.Unknown())) }),
        execute: async (_id, params) => invoke("components.call", params),
    });
}
