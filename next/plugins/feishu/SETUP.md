# 飞书机器人配置

每个机器人实例对应一个独立的飞书企业自建应用。请为两个测试实例分别创建应用，避免复用同一个应用的凭据：飞书长连接使用集群分发，同一应用的多个连接不会各自收到全部事件。

1. 在[飞书开发者后台](https://open.feishu.cn/)创建企业自建应用，开启机器人能力，并设置应用可用范围。在「凭证与基础信息」找到 App ID 和 App Secret；只在北极星本机窗口输入 Secret，不要发到聊天。
2. 在应用权限管理中，按使用场景申请：私聊接收 `im:message.p2p_msg:readonly`；接收群聊中 @ 机器人的消息 `im:message.group_at_msg:readonly`；以应用身份发送消息 `im:message:send_as_bot`。更新消息卡片时还需按实际接口权限要求开通相应权限。创建版本并发布，按企业设置完成管理员审核。
3. 在北极星组件管理中找到「飞书机器人」，打开实例视图，在「机器人身份」填写名称、App ID、App Secret 并保存，然后点击「连接」。为第二个机器人新建另一个实例并填写第二套应用凭据。
4. 客户端连接成功后，在飞书后台该应用的「事件与回调 → 事件配置」选择「使用长连接接收事件」并保存，订阅 `im.message.receive_v1`。飞书要求保存该模式时已有正常在线的长连接。事件订阅和权限等配置变更后按飞书提示重新发布。若要测试群聊，先将应用机器人加入目标群。若要接收卡片按钮交互，还需在「事件与回调 → 回调配置」选择长连接并订阅 `card.action.trigger`，按飞书提示发布。

飞书官方说明：[长连接接收事件](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-)、[机器人能力与发布](https://open.feishu.cn/document/client-docs/bot-v3/bot-overview?from=home)、[卡片回调](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)、[消息权限列表及旧权限下线说明](https://open.feishu.cn/document/develop-robots/add-bot-to-external-group?lang=zh-CN)。仅在明确指定目标后发送测试消息。
