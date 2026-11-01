# Polaris Agent 插件

此目录是新版 Agent 的独立接入包。Node.js 20+；无额外 npm 依赖，不调用模型或读取聊天历史。

Pi：`pi install /绝对路径/Polaris/next/integrations`，或 `pi -e /绝对路径/Polaris/next/integrations/pi/polaris.ts`。已有会话使用 `/reload`。Pi 1.4.x 的 `agent_settled` 自动上报每轮结束，最后一条 assistant 的文本来自 `message_end`，取消、失败和完成分别保存。`/polaris mark [名称]` 标记当前对话，或明确要求模型使用 `mark_current` 工具标记。连接持续到 session_shutdown；切换会话会关闭旧连接，投递前再次校验原生 session ID。发送必须明确选择 start 或 steer；start 只允许空闲会话，steer 只允许运行中会话。状态不匹配会拒绝，不自动更换模式。不展开命令和模板。

Codex：本目录自带独立本地 marketplace `polaris-agent-local`，插件名 `polaris-agent`。使用支持 plugin 命令的 Codex CLI 执行：

```bash
codex plugin marketplace add /绝对路径/Polaris/next/integrations
codex plugin add polaris-agent@polaris-agent-local
```

本机 CLI 帮助提供上述 marketplace add 与 plugin add 命令；真实桌面的安装、插件加载和 hooks 触发仍需宿主验收。安装后在桌面插件设置确认 Polaris Agent 已启用，按宿主提示审阅并信任 hooks，再打开新会话。安装不等于信任 hooks。目录 metadata、codex、skills、client.mjs 必须一起保留。使用 mark-current 技能明确标记当前对话。该命令只接受宿主提供的 CODEX_THREAD_ID；缺失时拒绝定位。MCP 连接可能共享，故不提供可猜测当前会话的 MCP 工具。

[Codex hooks](https://learn.chatgpt.com/docs/hooks) 的 Stop 是停止尝试，其他 hook 可要求继续，因此报告 unknown，不能代表最终静止或任务成功。Interrupt 报告 stopped。回复仅取 Stop 的 last_assistant_message。重复 Stop 去重，断线结束不重放。[App Server](https://learn.chatgpt.com/docs/app-server) 有 turn/completed，但插件没有假定可以连接桌面既有 app-server，也不会另起 agent 会话。

Codex 反向发送目前仅 Linux，使用隔离在 codex/desktop-ipc.mjs 的桌面私有 IPC，版本不兼容明确失败。按原始 session ID 做 owner discovery；只投递给该 owner，不打开历史或切换对话。调用方必须明确选择 start 或 steer，忙闲状态不匹配会拒绝，不改变模式重试。每分钟只探测这个会话的 owner，不读取历史或扫描其他会话；明确发现 owner 已关闭时注销；超时或传输异常时标记为未验证、停止发送能力并继续探测。空闲时间不会让仍然存活的 owner 过期。其他 OS 上 canSend=false，连接显示为宿主未验证，不宣称已实现反向发送。私有 IPC 当前代码基于旧插件已核对的 Linux Codex 0.160.1；本次仅假 IPC 验证，未对真实用户会话投递。真实插件加载、hooks 触发和各桌面版本仍需宿主验收。

先启动 Agent 组件。默认读取用户数据目录 polaris-agent/bridge/endpoint.json；可用 POLARIS_AGENT_ENDPOINT 显式指定。端点是同用户私有文件，连接仅限认证的 127.0.0.1 NDJSON，不继承旧协议或 relay 设置。重连只发布当前快照及仍活动的 run.started，不重放离线结束或自动重试发送。短 hooks 向本机会话 helper 转交数据，日常断线不输出提示、不更改宿主继续/停止决定。

验收：`node --test next/integrations/tests/*.test.mjs`。测试只用临时端点、假 Pi 宿主和假桌面 IPC，不启用或安装插件。

身份依据：官方 [exec_env.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec_env.rs) 将 CODEX_SESSION_ID 定义为共享根会话身份；[unified_exec](https://github.com/openai/codex/blob/main/codex-rs/core/src/unified_exec/process_manager.rs) 将当前 thread_id 注入 CODEX_THREAD_ID；[StopRequest](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/events/stop.rs) 的 hook session_id 类型是 ThreadId。因此标记使用 CODEX_THREAD_ID，与 hook 原生会话 ID 对应，不能用根会话身份替代。
