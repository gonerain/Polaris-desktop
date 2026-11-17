# 飞书 Agent

飞书与 Codex CLI 当前会话之间的后台消息通道。飞书文字消息只增量投递给 Codex；Codex 的输出与 Bridge 的结果回调转发到飞书。

需要支持应用后台、`dependencies` 和 `callbacks` 声明的宿主；配套源码见 [codex/feishu-agent-channel](https://github.com/gonerain/Polaris-desktop/tree/codex/feishu-agent-channel)。

## 连接

应用依赖飞书机器人、Codex CLI、日程、Agent Bridge 四个组件。组件或已绑定实例丢失时停止并报错；能力未连接或不可用时警告，实际调用失败保留记录，不终止后台。

在应用连接中设置四项能力：

| 别名 | 契约 | 用途 |
| --- | --- | --- |
| `feishuRead` | `polaris.feishu.read-messages@1` | 读取新增消息 |
| `feishuReply` | `polaris.feishu.reply@1` | 向飞书发送输出 |
| `codexGet` | `polaris.codex-cli.get@1` | 读取当前会话及完成输出 |
| `codexSend` | `polaris.codex-cli.send@1` | 增量输入 |

两项飞书能力来自同一个实例，两项 Codex 能力来自同一个实例。使用前配置好 Codex 工作目录、模型和工具环境，启动应用并通过正常授权确认。

一个应用连接一个 Codex CLI 实例和一个飞书会话或话题。首次安装定位到飞书消息末尾，不重放旧消息；此后的第一条入站文字消息建立飞书连接。其他会话的消息会明确标记为未投递，不混入当前上下文。出站消息和非文字消息不回灌给 Codex。

## 持续会话与增量输入

应用使用 CLI 已有的原生会话，不调用新建会话接口。空闲时以 `start` 开始新回合，运行中以 `steer` 追加新增文字。每次只传本条新增正文，不拼接或重放历史。既有历史、处理结果及 compact 后的上下文由原生 Codex 会话保留；`/compact` 等文字命令交给 CLI 自身处理。

Codex 如何执行任务由其当前环境决定，包括对日程、Bridge 的使用。应用不另设理解或决策环节。

## 输出与 Bridge 回调

应用以回合标识增量读取 Codex 的完成输出，持久化去重后发往已连接的飞书会话。首次接入不发送 CLI 已完成的历史输出；接入后、应用离线期间完成的输出会在恢复时继续处理。

应用声明 `bridge_output` 回调能力，契约为 `polaris.feishu-agent.bridge-output@1`。连接设置折叠区提供本应用的回调地址，可用于 Bridge `send` 的 `on_complete`：

```json
{"target":"本应用实例 ID","operation":"bridge_output","params":{}}
```

Bridge 返回的 `result` 必须包含 `deliveryId`、`sessionId`、`runId`、终态 `status`，以及可选的 `reply`、`replyTruncated`。应用保存输出后返回 `accepted: true`，表示已接管投递，不表示飞书已经收到。相同投递与回合的重复回调不会重复发送；相同标识但不同正文会报错。

回调输出只发往飞书，不作为 Codex 输入。用户在飞书回复后，才作为新的增量文字交给 Codex。调用回调入口仍须获得普通写权限；应用不会自动替调用方授予权限。尚未建立飞书连接时，已接管输出保留在队列中等待。

## 界面与失败处理

默认只显示运行开关、连接与当前会话、待投递数量，以及需要人工处理的事项。成功历史、能力明细、回调地址不平铺；连接警告和具体原因在设置或单项详情中查看。

- 明确被拒绝的输入或输出保留为失败，可手动重试或跳过。
- 投递结果未知时不自动重发；核对 Codex 或飞书后，选择确认送达或确认未送达并重发。
- 读取失败后暂停该读取，处理原因后点击“继续”；不阻断已接管的 Bridge 输出。
- 切换页面不停止后台；停止或重启保留游标、输入、输出和去重标识，不自动重放已接受的输入。
- 旧版本的完整状态保留在 `legacy` 中。未完成任务只在用户选择“交给 Codex”后转交；旧发送结果未知的任务须先核对，不自动迁移投递。

## 离线测试

```sh
PYTHONPATH=next .venv/bin/python -m unittest discover -s next/applications/feishu-agent/tests -v
```

测试使用假的网络与 Codex transport，并覆盖原生 CLI 会话复用、增量 steer、compact、结果回调、去重、恢复和精简界面；不调用真实模型或发送飞书消息。
