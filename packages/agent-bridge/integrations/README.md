# Agent Bridge 插件

此目录是新版 Agent 的独立接入包。Node.js 20+；无额外 npm 依赖，不调用模型或读取聊天历史。

Pi：`pi install /绝对路径/Polaris-agent/plugins/agent/integrations`，或 `pi -e /绝对路径/Polaris-agent/plugins/agent/integrations/pi/polaris.ts`。已有会话使用 `/reload`。Pi 1.4.x 的 `agent_settled` 自动上报每轮结束，最后一条 assistant 的文本来自 `message_end`，取消、失败和完成分别保存。`/polaris mark [名称]` 标记当前对话，或明确要求模型使用 `mark_current` 工具标记。连接持续到 session_shutdown；切换会话会关闭旧连接，投递前再次校验原生 session ID。发送必须明确选择 start 或 steer；start 只允许空闲会话，steer 只允许运行中会话。状态不匹配会拒绝，不自动更换模式。不展开命令和模板。

Codex：本目录自带独立本地 marketplace `polaris-agent-local`，插件名 `polaris-agent`。使用支持 plugin 命令的 Codex CLI 执行：

```bash
codex plugin marketplace add /绝对路径/Polaris-agent/plugins/agent/integrations
codex plugin add polaris-agent@polaris-agent-local
```

本机 CLI 帮助提供上述 marketplace add 与 plugin add 命令；真实桌面的安装、插件加载和 hooks 触发仍需宿主验收。安装后在桌面插件设置确认 Agent Bridge 已启用，按宿主提示审阅并信任 hooks，再打开新会话。安装不等于信任 hooks。目录 metadata、codex、skills、client.mjs 必须一起保留。使用 mark-current 技能明确标记当前对话。该命令只接受宿主提供的 CODEX_THREAD_ID；缺失时拒绝定位。MCP 连接可能共享，故不提供可猜测当前会话的 MCP 工具。

[Codex hooks](https://learn.chatgpt.com/docs/hooks) 的 Stop 是停止尝试，其他 hook 可要求继续，因此报告 unknown，不能代表最终静止或任务成功。Interrupt 报告 stopped。回复仅取 Stop 的 last_assistant_message。重复 Stop 去重，断线结束不重放。[App Server](https://learn.chatgpt.com/docs/app-server) 有 turn/completed，但插件没有假定可以连接桌面既有 app-server，也不会另起 agent 会话。

Codex 在线检测通过桌面私有 IPC 按原始 session ID 查询 owner：Windows 使用本机命名管道 `\\.\pipe\codex-ipc`，Unix 使用当前用户的 socket。启动、桥接重连时立即检测，之后每 15 秒检测一次。确认存在 owner 才显示在线；确认不存在则显示离线，并持续检测以支持自动恢复；超时、协议或传输错误则显示状态未知。在线检测不发送消息，也不扫描其他会话。轮次同步读取该会话宿主提供的内存快照，仅保留轮次编号、状态、同轮有长度上限的用户提问和最终回复，丢弃推理和工具输出，不加载历史文件。Windows 已在 Codex 26.1027.3384.0 上实测当前会话有 owner、不存在的会话无 owner。

Codex 反向发送支持 Linux 和 Windows，使用隔离在 codex/desktop-ipc.mjs 的桌面私有 IPC。调用方必须明确选择 start 或 steer，每次发送前重新查询宿主快照判断忙闲，不使用 helper 缓存的 runId 拒绝发送；真实忙闲状态不匹配才拒绝，不改变模式重试。启动和定时同步也会修复已登记轮次的残留 running、确认最终完成状态。在线检测与发送能力分别判断，只有 owner 确认在线且当前平台支持发送时才设置 canSend=true。Windows 已在 Codex 26.1027.3384.0 上通过真实模型、微信组件、Agent 和插件向当前运行会话发送 steer 消息，并获得 accepted 与实际 turnId；当前会话实际收到了该消息。start 与 steer 的请求版本、目标路由、中文内容、回执和断连不重试均有协议回归测试。新一轮 start 尚未对真实空闲会话投递验收。

先启动 Agent Bridge 组件。默认读取用户数据目录 polaris-agent/bridge/endpoint.json；可用 POLARIS_AGENT_ENDPOINT 显式指定。端点是同用户私有文件，连接仅限认证的 127.0.0.1 NDJSON，不继承旧协议或 relay 设置。重连只发布当前快照及仍活动的 run.started，不重放离线结束或自动重试发送。短 hooks 向本机会话 helper 转交数据，日常断线不输出提示、不更改宿主继续/停止决定。

验收：`node --test plugins/agent/integrations/tests/*.test.mjs`。测试只用临时端点、假 Pi 宿主和假桌面 IPC，不启用或安装插件。

身份依据：官方 [exec_env.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec_env.rs) 将 CODEX_SESSION_ID 定义为共享根会话身份；[unified_exec](https://github.com/openai/codex/blob/main/codex-rs/core/src/unified_exec/process_manager.rs) 将当前 thread_id 注入 CODEX_THREAD_ID；[StopRequest](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/events/stop.rs) 的 hook session_id 类型是 ThreadId。因此标记使用 CODEX_THREAD_ID，与 hook 原生会话 ID 对应，不能用根会话身份替代。

发送回执包含 `runId`，与 `run.started` / `run.ended` 使用同一身份：Codex 使用原生 turnId 的 SHA-256，Pi 在发送新轮次前预留运行标识。结果回传据此关联具体轮次，不用“会话最近一次结果”猜测。

### Codex helper 更新

Codex 插件从 `0.2.0` 开始使用 helper 控制协议。helper 身份包含版本及运行代码的内容摘要；安装器可执行稳定插件目录下的 `node codex/hook.mjs --upgrade-helpers`，通过标准输入传入 `{"sessions":[{"sessionId":"…","project":"…"}]}`。命令只操作这些会话的本插件私有管道，输出 `currentVersion`、`build` 及逐会话 `results`。

结果状态为 `current`（已运行当前代码）、`restarting`（正在换代）、`deferred`（当前投递完成后换代）、`legacy_requires_restart`（旧 helper 不支持安全换代）、`not_running`（未运行）或 `unavailable`（无法确认状态）。投递中的 helper 会先完成结果回执，再自行启动新版本；不会重放或重试消息。没有控制协议的旧 helper 保持连接，需要关闭并重新打开对应 Codex 会话后使用新版。安装器不得把此状态显示为升级完成。

只读查询使用相同输入执行 `node codex/hook.mjs --helper-status`，不会启动或退役 helper；另可返回 `update_available`，表示运行中的 helper 内容与当前插件不同。安装器应据此刷新状态，不能把上次 `deferred` 回执当作当前状态。升级命令也不会启动未运行的历史会话。

仅安装器显式执行 `--upgrade-helpers` 时触发换代。普通生命周期 hook 只转发事件，不因脚本内容差异换代，避免宿主尚在使用旧缓存 hook 时将新版 helper 降级。

## 0.3.0 许可与远程提问

新增同步 `PermissionRequest` hook，利用原生 hook 决定继续原操作；无明确远程回答时返回空决定，由宿主继续正常批准流程。长操作预览不截短后批准。等待期间 helper 更新会延后，直到交互结束；中断和会话结束使等待失效。

`node codex/hook.mjs --ask` 从 stdin 读取 `{"question":"问题","options":["选项一","选项二"]}`，使用 CODEX_THREAD_ID，等待当前已标记活动会话的真实用户回答，输出 `{"answer":"答案"}`。超时或不可用输出错误并返回非零退出码。该路径用于远程提问，未代理宿主原生提问框。对应 skill 在支持交互回调的投递中作为 skill 输入传给 Codex。

新增私有请求的端到端验收在 `tests/interaction-hooks.test.mjs`；Python 端另外验证请求归属、凭证、过期、断线与重启失效。所有自动化测试使用假宿主及临时端点。

结束通知提取同轮用户提问（最多 4000 字符）和最终回复（最多 8000 字符），超长明确标注；取不到内容时不借用其他轮次。PermissionRequest 处理前刷新宿主状态，宿主 approvalsReviewer=auto_review 时不创建人工交互或通知，不输出批准/拒绝决定；用户提问不受此过滤影响。
