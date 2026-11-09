# Codex CLI

Codex CLI 是多实例组件。每个实例配置一个绝对工作目录，使用本机已安装的 Codex CLI 和现有登录与配置。首次配置创建会话；组件重新启动时按保存的会话 ID 恢复。更换目录会创建新会话。需要本机 `codex` 命令。

界面支持消息、`/new`、`/compact`、中断及审批、提问。运行中的消息可以作为补充指导发送。不能开始第二个并发回合；用户可以等待当前回合结束。审批和提问等待用户回答。

操作：`get` 查询配置及状态，`configure(cwd)` 设置工作目录，`send(text, mode)` 发送（mode 为 `start` 或 `steer`），`new`、`compact`、`interrupt` 控制会话，`result(turn_id)` 查询结果。`send` 返回的 turnId 表示请求已接收；最终结果以 `turn.finished` 事件或 `result` 为准。事件包括 instanceId、threadId、turnId、status、reply 和 error，状态为 completed、failed 或 interrupted。事件在线投递，不重放；结果保存在实例数据目录。连接中断而结果未确认时显示 unknown。

Codex app-server 协议会随安装的 Codex 版本变化；本组件针对 Codex CLI 0.166.0 验证。
