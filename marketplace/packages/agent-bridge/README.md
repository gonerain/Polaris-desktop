# Agent Bridge

0.2.3 恢复 Pi 原生接入：逐条记录聊天输入，保存整轮最终回复，提供历史分页及开始、结束事件。Pi 扩展要求 Pi 1.5.2 的公开扩展 API。

Agent 管理已明确标记的 Pi、Codex 会话，接收宿主事件，显示每轮状态和宿主返回的回复，并在结束时提醒。标记保存在自己的本地数据目录；空闲、后台或连接断开不会删除标记。向会话发消息需要宿主仍打开、在线且报告发送能力。组件不会启动宿主。

从仓库根目录启动：

```bash
PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.agent.json
```

组件目录可单独加载。业务记录默认保存在 Windows `%LOCALAPPDATA%/polaris-agent/agent.json` 或 Linux `$XDG_DATA_HOME/polaris-agent/agent.json`（未设变量时使用 `~/.local/share`）。`create(data_dir=...)` 支持测试与独立装配。数据损坏会拒绝启动并保留原文件。

## 公开操作

- `get`：`{sessions, deliveries, requests, storageNotice, notificationFeed}`，含 Bridge 已记录的近期运行；原生完整历史使用 `history`。
- `sessions(marked?, include_result?)`：返回会话摘要数组，不含历史正文；`marked=true/false` 筛选标记状态。`include_result=true` 为每个会话附带最近已完成一轮的完整 `result`，不存在则为 `null`。`result.id` 是精确轮次标识，`result.historyIndex` 是保留历史中的序号（从 1 开始）；`runCount` 为历史总条数。`lastRun` 始终表示真正最新一轮，可能正在运行；与附带的已完成结果分开。
- `mark`、`unmark`、`status`：参数 `session_id` 为会话行的 `id`。
- `send`：`{session_id, text, mode, delivery_id?, on_complete?, on_interaction?}`（mode 为 `start` 新一轮或 `steer` 追加指导）。同一 `delivery_id` 重复调用返回原投递记录；换正文或会话会拒绝。`delivery` 用 `delivery_id` 查询状态。
- `history`：`{session_id, cursor?, limit?}`，从支持 `canReadHistory` 的在线会话按需读取当前分支的历史输入及回复。`limit` 为 1–100，默认 50；返回 `{items,nextCursor,leafId}`，`nextCursor` 非空时继续翻页。Pi 原生历史包含插件接入前及 compact 前的条目，不受近期运行缓存限制。输入为 `kind:input`，回复为 `kind:reply`，均保留原生 `id`、`timestamp` 和文本。新轮次通过不含正文的结束标记关联 `runId`，回复 `finality:confirmed`；旧日志只能提取输入之间最后一条终止助手消息作为候选，标记 `finality:unknown,status:unknown`，不能当成已确认终态。历史快照翻页期间允许追加消息；切换到其他分支须重新查询。读取不执行任务、不触发历史回调；单条内容超过桥帧容量时报错，不静默截断。
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

- `session.snapshot`：`title,cwd,canSend,canReadHistory?`，每次连接先报告当前会话。
- `run.started`：`runId`。
- `run.input`：`runId,id,text,timestamp`，Pi 每条实际进入会话的用户输入，按原生消息 ID 去重。
- `run.ended`：`runId,status,reply?,replyTruncated?,detail?`；仅确认整轮结束时报告 `completed`。
- `session.removed`：会话离线，保留标记与历史。

插件请求：`{type:"request",requestId,operation,params}`，响应为 `{type:"response",requestId,result}` 或 `error`。操作为 `session.mark/unmark/list/status/reply/send/delivery`；params 使用 `mode`（发送时必填 `start` 或 `steer`）、`sessionId`（原生会话 ID）、`runId`、`text`、`deliveryId`。请求只能作用于该连接身份的会话。

服务器发送 `{type:"command",command:"session.send",requestId,sessionId,text,mode}`。插件须核对当前宿主与原生会话，再回 `{type:"event",event:"command.result",requestId,status:"accepted|rejected|unknown",turnId?,runId?,detail?}`。不得猜测成功或自行重发。

历史读取使用 `{type:"command",command:"session.history",requestId,sessionId,cursor,limit}`；宿主校验绑定后返回 `{type:"event",event:"history.result",requestId,sessionId,result}` 或 `error`。响应必须属于原连接及会话，断线、连接替换或桥停止会明确终止待完成读取；没有等待用户的总时限，也不自动重试。

## Pi 接入与事件

使用 Pi 原生会话与公开扩展 API。`/polaris mark [名称]` 明确标记，`/polaris unmark` 取消标记，`/polaris status` 查看版本、会话、连接和最近错误。标记别名只保存为 Pi 的扩展元数据，不进入模型上下文。

本地输入、外部发送及 steer 补充都按条记录；同一活动直到 `agent_settled` 才结束，自动重试、compact 或继续执行不拆成额外任务。完成／失败／取消分别报告 `completed/failed/stopped`，没有最终回复时 `reply:null`；不转发中间回复、推理或工具输出，不另调用模型生成总结。实时结果超过 128000 字符会明确设置 `replyTruncated`，原生历史正文不因此截短。

Pi 的开始、输入、结束事件进入既有 `notifications.json` 事件日志，本地发起的轮次也上报。结果回调仍按投递与精确轮次关联。重连只发布当前活动或最近一个有持久化结束标记的终态，按原事件身份去重；不执行旧任务，不批量补发旧历史。Pi 的 `sendUserMessage` 返回 void，因此 `accepted` 仅确认扩展收到并调用了投递 API，实际开始以原生 `run.started` 为准；异步预处理错误由 Pi 报告，不能据此宣称已执行。

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
