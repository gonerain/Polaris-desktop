# Polaris Agent

模型配置、提示词、上下文和工具执行由本组件管理。普通聊天完成后直接返回；工具调用执行后将结果加入同一轮消息继续处理，没有固定的二次模型核对。

每轮最多 8 次模型请求、12 次工具调用，运行时间最多 300 秒，单次输出最多 4096 token。超过 6000 字符的工具结果提供预览和本轮引用，原始结果完整保留；使用 `read_result` 按 JSON Pointer 路径和范围读取。上下文超过预算时先收起较早结果，仍无法容纳时明确停止。

首轮自动提供有界的授权工具目录，带完整参数的操作可直接调用，其余按需查询帮助。大结果中的数组可用 `select_result(result_ref, path?, where?, fields?, offset?, limit?)` 批量筛选与提取顶层字段；筛选只做 JSON 标量精确匹配，不执行表达式，也不再次调用业务操作。

- `polaris.agent.status@1` 返回 `ready`、`model` 和配置提示，不返回密钥。
- `polaris.agent.reply@1` 接受 `text`、可选 `conversation`、`turn`、`parent` 和 `allowed: [{target,operation}]`，返回 `{text,turn}`。会话按请求来源安装、直接调用者和会话名隔离。
- `allowed` 只缩小本次委托范围。平台仍逐次检查实际授权；人工决定专用操作不会暴露为模型工具。相同写操作本轮去重，结果未知时不再次提交。
- 渠道可传入自己的 `control` 操作，接受 `active` 和 `prepare` 回调。模型不能选择回调地址。`parent` 指向上次确认送达的轮次，空字符串表示无历史；停止组件取消在途推理。

配置目录默认为用户数据目录下的 `polaris-assistant`。在 `model.json` 保存 `{"version":1,"provider":"bigmodel"}`，将对应密钥存入权限 0600 的 `bigmodel-api-key`。可选服务为 deepseek、bigmodel、zai；分别使用 `deepseek-api-key`、`bigmodel-api-key`、`zai-api-key`。

启动环境变量 `POLARIS_AGENT_MODEL_PROVIDER` 优先选择服务；密钥环境变量分别为 `DEEPSEEK_API_KEY`、`ZHIPUAI_API_KEY`、`ZAI_API_KEY`，优先于密钥文件。默认 deepseek，bigmodel/zai 使用 GLM-5.3-Flash。

GLM 默认使用 `low` 推理强度；可在 `model.json` 加入 `"reasoning_effort":"high"` 或 `"max"` 处理复杂任务。思考仍开启。DeepSeek 默认强度保持 `max`。

`model-usage.jsonl` 保存每轮请求的模型、实际 token 用量、请求大小和时间；不保存消息、工具结果或思考正文，文件权限 0600，最多保留当前和上一份 1 MiB 日志。
