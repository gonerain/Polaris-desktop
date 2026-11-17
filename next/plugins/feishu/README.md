# 飞书机器人组件

原生组件 `org.polaris.feishu-bot` 使用官方 `lark-channel-sdk==1.4.0` 与注册 SDK `lark-oapi==1.7.5`，支持多个机器人实例。每个实例拥有独立 App ID、凭据文件、消息数据库、游标和 SDK 子进程。通过组件管理器新建实例，在组件界面扫码创建或关联已有机器人；接入步骤见 [SETUP.md](SETUP.md)。

## 功能与接口

组件采用 `instances: {"mode": "multiple"}`。运行工厂 `polaris_feishu_bot:create(instance_context)` 使用平台提供的稳定 `instanceId` 和 `dataDir`。

| 操作 | 权限 | 参数 | 结果与契约 |
| --- | --- | --- | --- |
| `status` | read | 无 | 脱敏配置、连接状态、SDK 版本；`polaris.feishu.status@1` |
| `read_messages` | read | `after=0, limit=100, chat_id=None` | `{items, nextCursor}`；`polaris.feishu.read-messages@1` |
| `read_card_actions` | read | 同上 | 卡片操作记录；`polaris.feishu.read-card-actions@1` |
| `send` | write | `chat_id` 或 `target_id/target_type`；`text` 或 `message`；可选 `reply_message_id/reply_in_thread` | `{success, messageId}`；`polaris.feishu.send@1` |
| `reply` | write | `message_id`；`text` 或 `message`；可选 `reply_in_thread` | 引用本实例已收到或已发送消息；`polaris.feishu.reply@1` |
| `send_card` | write | `chat_id, card` | 发送 JSON 卡片；`polaris.feishu.send-card@1` |
| `update_card` | write | `message_id, card` | 更新本实例已发送的卡片；`polaris.feishu.update-card@1` |
| `upload_media` | write | `data_base64, file_name, kind='file', file_type=None` | 上传但不发送；返回 `media_key/kind/file_id/path/name/size` |
| `download_resource` | write | `file_key, message_id=None, resource_type='image', file_name=None` | 保存附件；返回 `file_id/path/name/size` |
| `read_attachment` | read | `file_id, offset=0, limit=262144` | 分块 `data_base64/offset/nextOffset/eof/name/size`；单块最大 1048576 字节 |
| `start_stream` | write | `chat_id` 或 `target_id/target_type`；`text='', title=''`；可选引用和话题选项 | 创建并发送流式卡片；返回 `stream_id/card_id/message_id` |
| `update_stream` | write | `stream_id, text` | 更新当前完整 Markdown 正文 |
| `finish_stream` | write | `stream_id, text=None` | 可写入最后正文并完成流式卡片 |

上述操作声明 `applicationBinding: instance`，应用可以按契约选择并授权具体机器人实例。消息和卡片回调通过无破坏游标读取，不需要应用事件订阅。每个消费者分别保存 `nextCursor`，下次将它作为 `after` 传入；空页保留原游标。`limit` 范围为 1–500。指定 `chat_id` 时只返回该会话记录。

消息记录包含 `cursor/messageId/chatId/sender/text/createdAt/direction/messageType`。入站 `normalized` 保存 SDK 完整规范化结构（content/conversation/sender/reply/mentions/resources 等），不保存 raw。入站记录还提供可选 `senderId/chatType/threadId/replyMessageId/mentions/resources`，具体字段取决于飞书事件类型；出站记录只保存本次发送可确认的信息。卡片记录保留操作值、标签、输入值、表单值、多选项和选中状态；不保存 SDK 原始 HTTP 对象。首次启动不会拉取飞书历史，只记录本实例实际接收到或发送成功的消息。

## 配置与生命周期

本机界面通过一次操作票据保留真实授权上下文，异步调用普通组件操作。`configure(name, app_id, secret)`、`connect`、`disconnect` 只接受当前组件本机视图动作，不向应用绑定开放。`status` 永不返回 App Secret；配置文件采用 0600 权限，目录默认 0700。空 Secret 表示保留同一 App ID 的原 Secret。

已配置实例的 App ID 不允许原地替换；更换机器人须新建实例。这样已有应用授权不会指向另一机器人。配置不自动连接；显式点击连接后保存连接意图，平台停止或重启保留此意图，下一次启动异步恢复连接。显式断开会取消恢复意图。恢复连接不会自动回复或发送消息。

SDK WebSocket 客户端拥有模块全局事件循环，令牌缓存也属于进程全局。组件因此为每个实例启动独立 SDK 进程，而组件本身保留原生 Qt 界面和平台实例协议。凭据通过私有 stdin 传给进程，不进入命令行。SDK 和传递依赖封装于组件的 `vendor/`；冻结宿主通过已有 `--component-python` 入口运行 worker。

普通 `send` 请求带 SDK 幂等 UUID；CardKit 引用发送接口不提供 UUID 参数。组件不会对超时消息自动重发；连接中断或发送超时表示结果可能不确定，必须先检查飞书会话。界面发送失败保留草稿，成功才清空。SDK 安全错误码用于诊断，HTTP 正文、凭据及原始异常不进入界面。

## 当前范围

支持文本、Markdown/富文本、图片、文件、音视频、卡片及 SDK 支持的名片/贴纸消息。`target_type` 为 `chat_id/open_id/user_id/union_id/email`，`chat_id` 和 `target_id` 二选一；`text` 和 `message` 二选一。`message` 使用 SDK JSON 形状；媒体 source 须为本实例 upload_media 返回的对应 img_/file_ 键，不接受本地路径或 URL。例如 `{"image":{"source":"img_..."}}`、`{"file":{"source":"file_..."}}`。引用须来自当前实例当前会话；`reply` 默认跟随原消息话题，可用 `reply_in_thread` 覆盖。

已发送附件的 `canonicalContent/resources` 保存飞书消息响应中的实际内容与资源键；按消息下载时以该返回值或入站资源键为准，不能假定上传键与消息资源键相同。

附件通过 base64 上传，下载保存于当前实例的私有附件目录；公开 API 只按本实例 `file_id` 读取文件，不接受任意读取路径。分块接口方便应用取得完整文件，界面可选择位置保存附件。定向发送未返回真实 chat_id 时，记录保留 targetId/targetType，chatId 为空，不冒充会话 ID。

流式卡片必须分次调用 `start_stream` → 多次 `update_stream` → `finish_stream`。每次更新正文是当前完整 Markdown；序号在请求前持久消耗，成功才更新本地已确认正文及完成状态，失败不自动重发。状态随实例保存；`status.activeStreams` 返回未完成卡片供重新打开后继续。消息记录的 `streamId/streamState` 和正文同步更新并推进游标。没有自动过期或自动完成。组件不包含会议或办公 API。

依赖发行许可证为 `MIT AND BSD-3-Clause`，许可证材料和锁定依赖见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `dependencies.lock.json`。当前构建包包含 Linux x86_64 二进制依赖。

## 离线验证

`tests/test_backend.py` 覆盖实例隔离、配置权限、游标分页与去重、连接恢复、官方 SDK 消息和卡片模型、官方发送参数解析及返回值、双 worker PID 和退出。网络边界使用离线替身；这些测试不能证明飞书凭据、应用权限或真实消息投递成功。真实连接须由用户在组件界面配置后验证。

配置完成后，点击“打开机器人私聊”进入桌面飞书，或点击“手机扫码进入”用手机飞书打开该机器人的聊天。发送消息后，可在此实例查看和回复。
