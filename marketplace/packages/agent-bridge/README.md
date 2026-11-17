# Agent Bridge

0.2.2 恢复 Codex 结束通知流；当旧版状态缺少通知记录但原通知文件仍存在时，保留原通知流身份和事件序号。暂停期间的历史运行不会自动补发。

Agent 管理已明确标记的 Pi、Codex 会话，接收宿主事件，显示每轮状态和宿主返回的回复，并在结束时提醒。标记保存在自己的本地数据目录；空闲、后台或连接断开不会删除标记。向会话发消息需要宿主仍打开、在线且报告发送能力。组件不会启动宿主。

从仓库根目录启动：

```bash
PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.agent.json
```

组件目录可单独加载。业务记录默认保存在 Windows `%LOCALAPPDATA%/polaris-agent/agent.json` 或 Linux `$XDG_DATA_HOME/polaris-agent/agent.json`（未设变量时使用 `~/.local/share`）。`create(data_dir=...)` 支持测试与独立装配。数据损坏会拒绝启动并保留原文件。

## 公开操作

- `get`：`{sessions, deliveries, requests, storageNotice, notificationFeed}`，含完整会话历史。
- `sessions(marked?, include_result?)`：返回会话摘要数组，不含历史正文；`marked=true/false` 筛选标记状态。`include_result=true` 为每个会话附带最近已完成一轮的完整 `result`，不存在则为 `null`。`result.id` 是精确轮次标识，`result.historyIndex` 是保留历史中的序号（从 1 开始）；`runCount` 为历史总条数。`lastRun` 始终表示真正最新一轮，可能正在运行；与附带的已完成结果分开。
- `mark`、`unmark`、`status`：参数 `session_id` 为会话行的 `id`。
- `send`：`{session_id, text, mode, delivery_id?, on_complete?, on_interaction?}`（mode 为 `start` 新一轮或 `steer` 追加指导）。同一 `delivery_id` 重复调用返回原投递记录；换正文或会话会拒绝。`delivery` 用 `delivery_id` 查询状态。
- `result`：`{session_id, run_id?, completed_only?}`，缺省返回最近一轮；运行中或没有最终文本时 `reply` 为 `null`。显式设置 `completed_only=true` 才查找最近已完成的一轮，没有则返回 `null`，不能同时指定 `run_id`。

投递 `pending/accepted/rejected/unknown` 与运行 `running/completed/failed/stopped/unknown` 分开。`accepted` 只表示宿主接收。30 秒未收到回执或连接中断、替换时，未确认投递变为 `unknown`，不会重试。每轮首个结束事件生成一次提醒。停止钩子不能证明最终完成时应报告 `stopped` 或 `unknown`。

## Codex 插件

界面右上角「Codex 插件」打开设置，提供「安装到 Codex」「更新插件」「检查状态」。检查和安装在后台执行；只有点击安装或更新才调用 Codex 安装命令。需要本机 Codex CLI 和 Node.js 20+。

随包资源来自 `plugins/agent/integrations`，安装时复制到 Agent 数据目录下的 `codex-plugin/marketplace`，由 Codex 管理安装副本。移动软件目录后仍使用该稳定来源。设置显示随包和安装版本、插件启用状态及依赖检查结果。启用与 hooks 信任按 Codex 提示操作，安装成功不代表 hooks 已获信任。

`codex_plugin_status` 是独立只读操作，`codex_plugin_install` 是独立写操作，安装和更新共用后者。Agent 视图明确声明这两项权限，`get` 权限不会授权安装。没有自动安装或后台升级。

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
PYTHONPATH=plugins/agent python -m unittest discover -s tests -v
```

可选结果回传：`send` 接受 `on_complete={target, operation, params}`。调用方提供回传地址，组件不依赖任何具体接收方。宿主回执必须带与运行事件完全一致的 `runId`；仅当该投递已接收、该轮次确定完成/失败/停止时回传 `{...params, result:{deliveryId,sessionId,runId,title,status,reply,replyTruncated}}`。回传操作返回 `accepted:true` 表示已接管结果。未配置地址的任务行为不变，未知结果不触发结束回传。地址、处理进度和原请求的有限授权保存到本地；接收方暂不可用时等待恢复，不确定是否执行时不盲目重试。

## 用户交互

`requests(session_id?)` 列出已标记在线会话中待处理的许可或问题；`status` 的 `pendingRequests` 提供该会话的列表。查询不返回响应凭证。

`send` 可带 `on_interaction={target,operation,params}`。原投递接收且对应轮次发起交互后，使用原请求的有限授权回传 `{...params,result:{id,sessionId,deliveryId,runId,kind,prompt,options,expiresAt,responseToken}}`。接收方须直接展示并采集真实用户输入，不能让模型代选。`respond(request_id,response_token,answer)` 校验原回调接收方、一次性凭证、会话状态与有效期；许可答案仅允许 `allow` 或 `deny`，问题答案为文字。该操作标记 `humanOnly`，响应凭证不可放入模型工具结果。

宿主私有请求新增 `interaction.open/status/close`，始终使用当前连接自己的原生 `sessionId`、活动 `runId`。断线、轮次结束、过期或组件重启会使未完成请求失效。回答后不能改选或重复批准。桥不会因等待超时而自行选择答案。

随包 Codex 插件 0.3.0 增加 `PermissionRequest` hook，将完整且不超过 1400 字符的操作请求转成交互，最多等待 110 秒。用户回答通过原 hook 的原生批准/拒绝输出继续原请求；未回答、不支持或预览过长时不作决定，仍交由 Codex 正常批准流程处理。只有经过支持版本、已启用且受信任的 hooks 才能触发。更新组件后需在“Codex 插件”设置中执行更新，并按状态提示处理旧会话连接。

带交互回调的 Codex 投递附带 `remote-interaction` skill。Agent 可用其中的远程提问命令等待接收方回答；返回的答案继续当前轮次。该工具不自动接管已经打开的 Codex 原生提问框。原生框的服务端请求回传仍取决于宿主接口支持，不能用发送普通消息冒充已回答。

## Codex 被动通知事件（不授予控制权）

Agent 从已接入适配器实际收到的 Codex 确定终态（completed/failed/stopped）和
interaction.open 提问/审批请求写入自己的持久化通知日志，不要求标记或原始远程投递。
同目录 notifications.json 是只含通知数据的 0600 导出，不包含 responseToken；
get 返回 notificationFeed.path/pendingExport/eventCount。导出失败由后台工作线程修复，
重启也会从主状态恢复。候选 Stop/unknown 不生成成功通知。

未标记 Codex 会话的交互返回 notificationOnly=true，记录后立即交回原生处理；
不会获得回复凭证，send/respond 仍保留原有标记、在线和授权校验。其他适配器的
未标记交互限制不变。已标记会话原有回调与控制流程不变。

这不是所有宿主的全局事件接口：必须加载并信任 hooks，且通过现有适配器的 owner/
运行身份检查。当前捕获 PermissionRequest 与显式远程提问 helper，未接管任意
Codex 原生提问框。适配器未提供的事件、离线期间未送到 Agent 的 hook、云端及其他
机器的会话不能凭空恢复。通知日志尚未自动压缩；不要将它当作无限期生产队列。
