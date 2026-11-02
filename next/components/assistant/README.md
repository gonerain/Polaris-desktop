# Polaris Agent

模型配置、提示词、上下文和工具执行都在此组件。设置启动进程的 `DEEPSEEK_API_KEY`，将 Polaris Agent 加入画布即可对话。直接聊天默认只使用模型。勾选“使用已授权工具”才会把当前请求已有权限的组件操作交给模型；每次工具调用仍由平台检查授权。

- `polaris.agent.status@1`（读）返回 `ready`、`model` 和配置提示，无密钥值。
- `polaris.agent.reply@1`（写）接受 `text`、可选 `conversation` 和本次允许的 `allowed: [{target,operation}]`，返回 `{text,turn}`。会话在内存中按请求来源、直接调用者和会话名区分。
- 对有投递回执的渠道，可传 `turn` 和上次确认送达的 `parent`，空字符串表示无历史。可选 `control` 是直接调用组件自己的回调操作，`active` 检查本轮是否仍有效，`prepare` 为支持结束回执的写操作附加渠道回调。模型不能挑选回调目标。停止组件会取消在途推理并清除上下文。

Agent Bridge 是独立的 Codex/Pi 会话接入组件。它保留原来的 `org.polaris.agent` 安装 ID 和数据格式。
