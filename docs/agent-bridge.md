# Agent 组件与本机协议 v1

## 边界

Agent 组件展示会话、运行结果和结束提醒，并向声明发送能力的已接入会话发送文字。核心按连接实例与会话 ID 路由，具体宿主协议由来源适配器实现。
Pi 是第一个已实现的外部适配器；其他来源只需遵守同一协议，无须向核心登记 Agent 类型。
Codex 本地插件同样位于 `integrations/`：生命周期 hooks 通过每会话助手上报，MCP 工具使用独立连接。
Codex Stop 没有最终 settled 保证，适配器上报 unknown；取消上报 cancelled，具体限制见接入说明。
代码不解析终端、不上传提示词或日志，不创建第二个 AI 会话。Codex 在 Stop 上报最新助手回复，供 Agent 组件按读取权限查询。

组件接口与会话上报独立。同一连接可只使用其中一种能力：调用组件不必注册 Agent 会话。
`ComponentRegistry` 是显式业务入口登记表，不是动态插件加载器、消息总线或任意 QObject 方法代理。

## 使用

- 点击桌宠打开平铺画布，没有顶部页签；日程和 Agent 都通过 `ComponentBoard.request` 申请 cell。
- 默认容量为 2×2 四格：日程申请两个相邻 cell（仍为528×300），Agent 申请一个 cell（260×300），余下一格留空。
  每个组件有32px通用标题条，整张默认画布528×672；可拖动换位，`−/+` 最小化/恢复，保留原占格和同一实例。
  容量与占用数量独立，未申请的 cell 不自动填充；多格、不规则占格仍按原分配协议处理。
  画布首次展开时创建，收起保留实例和草稿；业务模型和组件 API 不依赖画布创建。
- Agent 单格面板的 `↗` 打开独立完整视图，返回时不重分配 cell。也可用右键或托盘的“Agent 会话”。
- 在 Agent 完整视图的“组件访问”中对每个插件、每个组件选择未授权、只读或允许修改。
  默认全部未授权；声明固定 `pluginId` 的插件授权保存到 `bridge/permissions.json`，同身份连接共享，断线、重启或插件 reload 后继续有效；可在面板撤销，离线插件也保留授权项。未声明插件身份的旧客户端仍仅当前连接有效。
  插件身份由同用户本机客户端自报，不是签名身份；新客户端通过 `pluginId` 匹配授权。为接续仍在运行的旧 Codex 插件，旧版固定名称 `Codex hooks` / `Codex tools` 归入 `polaris.codex`；显式声明其他身份的连接不会被归并。Codex 的授权面板统一显示“Codex 插件”，只保留一项。
- 每轮结束事件直接触发「会话标题」的会话结束了，显示6500毫秒，长标题省略。
  紧凑时自动弹桌宠气泡，展开时先显示界面内短提示，收起后继续显示剩余时间。
  无须模型调用工具或授予组件权限，不另发 Agent 系统通知，不抢焦点、不切页、不触发桌宠动作。
- 最近十次结束结果仅在内存保留，退出即清空；不是历史会话同步或持久消息队列。

Pi 安装与 WSL 配置见 [`integrations/README.md`](../integrations/README.md)。

## 连接与认证

同环境使用 Qt LocalSocket：Windows 命名管道，Linux Unix socket。只传 UTF-8 JSON Lines，
每条消息以 `\n` 结尾，含换行最多 65,536 字节。不监听 TCP。

端点文件：Qt `AppLocalDataLocation` 下的 `bridge/endpoint.json`：

- Windows：通常 `%LOCALAPPDATA%\Polaris\Polaris\bridge\endpoint.json`。
- Linux：通常 `${XDG_DATA_HOME:-$HOME/.local/share}/Polaris/Polaris/bridge/endpoint.json`。

```json
{"protocol":1,"address":"实际本机管道或套接字地址","token":"64位随机十六进制字符串"}
```

文件原子更新。Linux 桥目录 0700、文件 0600；套接字优先放安全的 XDG 运行目录，
否则放随机创建的用户私有临时目录，不复用公共固定路径。
Windows 使用用户配置目录的 ACL，命名管道通过 `UserAccessOption` 限制当前用户连接。
这不是对同一用户恶意进程的沙箱；来源名称自报，不能当成身份认证证书。

首次请求必须认证，5 秒内未认证关闭：

```json
{"id":"hello-1","method":"hello","params":{"protocol":1,"token":"端点中的密钥","instanceId":"实例随机ID","name":"接入来源显示名","pluginId":"polaris.codex"}}
{"id":"hello-1","ok":true,"result":{"protocol":1,"heartbeatSeconds":15}}
```

一个连接绑定一个实例，可包含多个会话；同一实例不能同时占两个连接。
实例 ID 最长128字符，name 最长64字符。不接受空白身份字符串。
密钥不要放进模型上下文、项目文件或日志。

## 请求、响应与组件能力

请求 ID 是最长128字符的非空字符串。结果使用统一格式：

```json
{"id":"1","method":"components.list","params":{}}
{"id":"1","ok":true,"result":[{"id":"calendar","name":"日程"}]}

{"id":"2","method":"components.help","params":{"component":"calendar"}}
{"id":"3","method":"components.call","params":{"component":"calendar","operation":"task.create","args":{"title":"整理资料","date":null}}}

{"id":"3","ok":false,"error":{"code":"permission_denied","message":"请用户在 Polaris 授权"}}
```

发现与 help 不读取业务内容，无需组件授权；实际调用必须检查组件级权限。
每个组件自己声明操作、read/write、参数、返回值和示例，并自行校验参数。
内部受信任组件也可直接使用同一个登记表，不必绕进程通信；调用方仍需显式给定权限。

桌宠登记为 `pet`，提供 `say`（write）：纯文字短消息，最多120字符；`durationMs` 为1000..15000的整数，默认6500。
紧凑时显示桌宠气泡，屏幕上沿优先放在下方；展开时显示界面内短提示，不强制收起、切页或抢焦点。
返回 `{shown,presentation,durationMs}`；新消息替换旧消息，不播放语音、不自动转发聊天。
此主动调用接口是可选能力；Agent 结束气泡由生命周期事件直接触发，不经过 `pet.say` 或其访问授权。

Agent 自身也登记为 `agents` 组件，提供只读 `session.list / result.list`；读取其元数据同样需要授权。
日程登记为 `calendar`，提供主任务、一级子任务、笔记和日终整理，准确参数与返回值以 help 为准；
完整操作表、删除示例及并发编辑说明见 [日程组件 API](calendar-api.md)。
查询分页；默认不读取笔记正文，搜索笔记也须显式开启。创建默认进收集箱，有时间必须有日期；
经 API 移回收集箱时清除时间。主任务删除可按原 ID 撤销最近一次；子任务删除不支持撤销。
所有修改走唯一 `CalendarTaskStore`，不会切换用户浏览日期，也不直接读写 `tasks.json`。

写操作返回 `applied` 与 `persisted`：

- `applied=true` 表示内存已应用，**不要再创建一次**。
- `persisted=false` 表示尚未写入磁盘；读取 `storageError`，让用户在日程中重试保存。
- 已有存储错误时拒绝新的外部写操作，不掩盖损坏保护或保存失败。

同一连接缓存最近16个带 ID 请求的响应。相同 ID + 相同原始消息返回旧结果；
相同 ID 换内容拒绝。不承诺跨连接或无限历史的 exactly-once。
客户端不自动重试业务请求；超时、断连后写操作可能已经应用，必须先查询。
结果超过单帧限制会返回 `result_too_large`；查询缩小 limit，写调用不得因此盲目重放。

## 会话事件

单向事件没有请求 ID；格式错误时关闭连接，适配器修复后重连、发送当前快照。

```json
{"event":"session.snapshot","data":{"sessionId":"opaque-session-id","source":"任意来源","name":"会话名称","project":"源环境中的项目路径","state":"idle","runId":"","outcome":""}}
{"event":"run.started","data":{"sessionId":"opaque-session-id","runId":"unique-run-id"}}
{"event":"run.ended","data":{"sessionId":"opaque-session-id","runId":"unique-run-id","outcome":"ended"}}
{"event":"session.removed","data":{"sessionId":"opaque-session-id"}}
```

- 快照必填 sessionId、source、name、project、state；project 可为空，只显示，不用于宿主文件访问。
- sessionId 最长256字符，source 最长64，name 最长128，project 最长4096。
- state 只接收 idle / running；断连状态由服务端产生，不由客户端假冒。
- running 快照必须携带非空 runId，最长128字符；每个会话每轮使用唯一 ID。
- 同一逻辑运行里的自动重试/恢复继续沿用 runId；结束只能匹配当前运行。
- outcome 为 ended / failed / cancelled / unknown。ended 只表示正常结束，**不保证目标达成**。
- 快照本身永不提醒；结束事件按实例+会话+运行 ID 去重，保留最近1024个结束身份。
- 正常注销移除会话，最近结果仍可查看；异常断连会话短暂保留30秒，再移除，不冒充完成。

15秒一次心跳：

```json
{"id":"hb-1","method":"heartbeat","params":{}}
```

45秒无有效消息关闭连接；仅临时连接授权随之清除，插件授权继续保留。Polaris 重启后重新读取端点、认证、发送当前快照；
不重放离线事件，不补报旧结束通知。Node 客户端重连间隔1秒渐增到10秒。
服务端限制32连接、128会话、单连接每5秒200条消息，并限制读写缓冲与未认证存活时间。

## Codex 会话 ID 与发送通道探测

Codex 插件直接将 hook 的原始 `session_id` 上报为 `sessionId`（最长256字符），
AgentHub 原样保存，仍用连接实例与会话 ID 共同标识会话。助手管道名称与运行 ID 的哈希不受影响。

2026-10-29 本机探测与验证结果（CLI 0.155.1，桌面捆绑 Codex 0.160.1）：

- 官方 app-server 控制套接字的 WebSocket 握手、初始化和 `thread/read` 成功，能读到当前会话 ID、标题和项目。
  但该服务的 `thread/loaded/list` 为空，当前会话状态为 `notLoaded`；不能据此认定它持有桌面端当前运行。
- 桌面端私有 IPC 位于 `$CODEX_HOME/ipc/ipc.sock`，使用4字节小端长度前缀和 JSON 消息，
  与 app-server 的 WebSocket 协议不同。初始化后，`thread-owner-discovery`（version 1，
  参数 `hostId: "local"` 与 `conversationId`）成功定位当前会话的桌面持有者。
- 本机桌面代码提供 `thread-follower-start-turn`（version 2）和 `thread-follower-steer-turn`（version 1），
  可按持有者路由发送请求；这是桌面内部协议，不是已保证稳定的公开插件接口。
  已通过执行中当前会话验证 `steer` 的真实投递，并通过临时 Qt 桥 → 插件助手 → 桌面 IPC → 当前会话验证完整链路，
  返回 `accepted` 与真实 `turnId`，原会话和模型均收到测试标记。`start` 已通过假桌面 IPC 检查，尚未实机验证空闲会话的新一轮发送。
- CLI 提供 `codex queue --thread <ID> --message <TEXT>`，本次仅核对帮助和官方文档，未执行投递。

接口参考：[App Server](https://learn.chatgpt.com/docs/app-server)、
[codex queue](https://learn.chatgpt.com/docs/developer-commands#codex-queue)。

## 发送文字与查询回执

来源在 `session.snapshot` 中可选声明 `sendModes: ["start", "steer"]`，不声明则不可发送。
当前 Codex 发送适配仅在 Linux 启用，连接同用户的私有桌面 IPC；不会另起 Codex 运行来恢复历史。

Agent 组件提供：

- `session.send`（write）：`{instanceId,sessionId,text,mode}`，text 最长8000字符，mode 必须明确为 start 或 steer。
- `session.delivery`（read）：`{deliveryId}`，返回目标、状态、真实运行 ID 和错误代码。

```json
{"component":"agents","operation":"session.send","args":{"instanceId":"从session.list选定的连接ID","sessionId":"原始会话ID","text":"请继续检查","mode":"start"}}
```

写操作仍受当前调用连接的 Agent 组件修改授权约束。`session.send` 返回 `{deliveryId,status,applied:true}`，
此处 applied 只表示已提交发送指令，必须用 `session.delivery` 查询投递结果；不表示模型已收到或任务已完成。

- `sending`：等待目标回执。
- `accepted`：目标已接受消息，附 `turnId`；不表示本轮成功结束。
- `failed`：未投递，例如未找到持有者、目标忙碌或不支持模式。
- `unknown`：发出后断连、超时或收到无法确认是否执行的错误；不得自动重发。

同一会话最多一个待回执发送；核心最多保留128条发送记录，不保存消息正文，25秒无回执标为 unknown。
回执只能由接收命令的连接提交，且必须匹配发送凭据与会话 ID。状态为 unknown 时仍可接受迟到回执。
助手在20秒内结束一次 IPC 请求，不自动重试、不自动切换 start/steer，不重放断线期间的命令。
助手最多记住1024个已尝试命令 ID（只保留参数摘要和回执），重复 ID 不再投递；容量满后拒绝新命令，
重连保留该去重记录。此约束仅覆盖同一助手生命周期，不承诺跨重启去重。

本机反向帧：

```json
{"command":"session.send","id":"delivery-id","params":{"sessionId":"native-session-id","text":"请继续检查","mode":"start"}}
{"event":"command.result","data":{"deliveryId":"delivery-id","sessionId":"native-session-id","status":"accepted","turnId":"native-turn-id"}}
```

反向命令仅发到会话所属的已认证连接。Codex 助手校验会话、容量和发送状态，再定位桌面持有者，使用其内部 IPC 投递。
start 在助手认为仍在运行时返回 session_busy；steer 由桌面端校验是否存在执行中的一轮。空闲与运行状态可能改变，
失败不自动改成另一种模式。发送界面尚未加入，当前通过组件 API 调用。

## Pi 适配

`session_start` 建立连接，`session_shutdown` 幂等清理，改名更新快照。
`agent_start` 开始一轮；重复的 agent_start 不换运行 ID。
只有 `agent_settled` 才结束：结合 aborted 和本轮最后 assistant 的 stopReason 分类，
无法确认就报告 unknown。`agent_end` 不是最终结束，不用于提醒。

插件只提供三个通用工具：`polaris_components / polaris_help / polaris_call`，没有日程类型或存储路径逻辑。
连接失败不阻塞 Pi 启动，不自动启动 Polaris，不创建模型请求，也不向每轮提示注入组件数据。

## WSL 中继

`Polaris.exe --bridge-stdio`（Linux 同名程序也支持）是无 GUI 的本机连接助手：
标准输入/输出转发 JSON Lines，读取宿主自己的端点文件，为首次 hello 注入宿主密钥。
它不占第二个应用锁、不打开任务库或窗口，不承担 Agent 业务。

适配器显式配置命令参数数组 `POLARIS_RELAY`，无 shell 拼接、不自动猜安装位置、发行版或 IP。
Windows interoperability 被禁用时接入失败，不退回网络监听。
中继借用宿主当前用户身份，不把 Windows 用户与 WSL 用户当作互相隔离的安全沙箱。

## 验证方式

Agent 组件提供 `session.status` 实时摘要：从与面板相同的 AgentHub 统计全部会话的
`running / idle / disconnected` 数量，附查询时间和最多20条执行中会话。
`state` 表示当前状态，`outcome` 仅表示上一轮结果，不能据此推断当前是否空闲。

只用临时内联诊断、内存或临时存储，不新增测试套件，不接触真实用户日程。
覆盖陌生来源、多实例同会话ID、授权弹层、非法输入、重发、超时存活、重连、
Pi 官方扩展加载器和生命周期回调，以及 Windows↔WSL 中继。没有通过真实收费模型请求来验证生命周期。

## 查询最近结束回复

通过 `components.call` 调用 `agents / session.reply`：

```json
{"component":"agents","operation":"session.reply","args":{"instanceId":"session.list 返回的连接ID","sessionId":"原始会话ID"}}
```

返回 `instanceId / sessionId / available`；已记录结束事件时另附 `runId / outcome / endedAt`。
有正文时附 `reply / truncated`；没有结束记录时 `reason: no_completed_run`，
最新一轮结束但来源未提供正文时 `reason: reply_not_reported`，不会回退到更早一轮的正文。
新一轮正在执行时仍可查询上一轮结束回复，`runId` 用于区分。

Codex 仅从 Stop 的 `last_assistant_message` 取正文，最多8000个 Unicode 字符，超出部分标记 `truncated: true`；
缺失字段不会读取聊天日志补全，也不会用提示词代替。Stop 不保证最终 settled，因此 `outcome` 仍为 unknown。
核心最多保留128个会话的最近结束回复，仅保存在本次应用内存，退出即清空；升级前的回复不会追溯补录。
`result.list` 的结束摘要另附 `instanceId / sessionId / runId / replyAvailable`，用于选定目标后查询正文。
此接口使用 Agent 组件已有的读取授权。
