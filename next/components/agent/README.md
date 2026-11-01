# Agent

Agent 管理已明确标记的 Pi、Codex 会话，接收宿主事件，显示每轮状态和宿主返回的回复，并在结束时提醒。标记保存在自己的本地数据目录；空闲、后台或连接断开不会删除标记。向会话发消息需要宿主仍打开、在线且报告发送能力。组件不会启动宿主。

从仓库根目录启动：

```bash
PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.agent.json
```

组件目录可单独加载。业务记录默认保存在 Windows `%LOCALAPPDATA%/polaris-agent/agent.json` 或 Linux `$XDG_DATA_HOME/polaris-agent/agent.json`（未设变量时使用 `~/.local/share`）。`create(data_dir=...)` 支持测试与独立装配。数据损坏会拒绝启动并保留原文件。

## 公开操作

- `get`：`{sessions, deliveries, storageNotice}`；`sessions` 返回会话数组。
- `mark`、`unmark`、`status`：参数 `session_id` 为会话行的 `id`。
- `send`：`{session_id, text, mode, delivery_id?}`（mode 为 `start` 新一轮或 `steer` 追加指导）。同一 `delivery_id` 重复调用返回原投递记录；换正文或会话会拒绝。`delivery` 用 `delivery_id` 查询状态。
- `result`：`{session_id, run_id?}`，缺省返回最近一轮；运行中或没有最终文本时 `reply` 为 `null`，不会返回上一轮回复。

投递 `pending/accepted/rejected/unknown` 与运行 `running/completed/failed/stopped/unknown` 分开。`accepted` 只表示宿主接收。30 秒未收到回执或连接中断、替换时，未确认投递变为 `unknown`，不会重试。每轮首个结束事件生成一次提醒。停止钩子不能证明最终完成时应报告 `stopped` 或 `unknown`。

## 私有本机桥协议 v1

桥仅绑定 `127.0.0.1` 随机 TCP 端口。`bridge/endpoint.json` 包含 `version,host,port,token`；目录权限 0700、文件 0600（Windows 的访问控制沿用用户目录）。token 每次启动重新生成，不写入业务记录。仅持有私有端点文件的本机程序可连接。该桥不提供平台操作代理。

一行一个 JSON，最多 1 MiB（包括换行）。首帧：

```json
{"type":"hello","token":"…","adapter":"pi","clientId":"host-instance-id"}
```

成功回 `{"type":"hello","ok":true}`。同一 adapter/clientId 的新连接替换旧连接；一个数据目录只允许一个桥实例。端点原子替换，不跟随端点符号链接。clientId 必须唯一标识宿主实例并跨插件重连稳定。会话身份为 adapter/clientId/原生 sessionId 三元组。

事件帧通用字段 `type:event,event,sessionId`：

- `session.snapshot`：`title,cwd,canSend`，每次连接先报告当前会话。
- `run.started`：`runId`。
- `run.ended`：`runId,status,reply?,replyTruncated?,detail?`；仅确认整轮结束时报告 `completed`。
- `session.removed`：会话离线，保留标记与历史。

插件请求：`{type:"request",requestId,operation,params}`，响应为 `{type:"response",requestId,result}` 或 `error`。操作为 `session.mark/unmark/list/status/reply/send/delivery`；params 使用 `mode`（发送时必填 `start` 或 `steer`）、`sessionId`（原生会话 ID）、`runId`、`text`、`deliveryId`。请求只能作用于该连接身份的会话。

服务器发送 `{type:"command",command:"session.send",requestId,sessionId,text,mode}`。插件须核对当前宿主与原生会话，再回 `{type:"event",event:"command.result",requestId,status:"accepted|rejected|unknown",turnId?,runId?,detail?}`。不得猜测成功或自行重发。

测试使用临时目录与临时 loopback 连接：

```bash
PYTHONPATH=next python -m unittest discover -s next/components/agent/tests -v
```

可选结果回传：`send` 接受 `on_complete={target, operation, params}`。调用方提供回传地址，组件不依赖任何具体接收方。宿主回执必须带与运行事件完全一致的 `runId`；仅当该投递已接收、该轮次确定完成/失败/停止时回传 `{...params, result:{deliveryId,sessionId,runId,title,status,reply,replyTruncated}}`。回传操作返回 `accepted:true` 表示已接管结果。未配置地址的任务行为不变，未知结果不触发结束回传。地址、处理进度和原请求的有限授权保存到本地；接收方暂不可用时等待恢复，不确定是否执行时不盲目重试。
