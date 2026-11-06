# 文本工作室示例

这个目录包含两个可独立安装的包：`component` 提供文本整理和规则词频统计；`application` 用自己的 QML/JavaScript 实现双栏编辑器、字符统计、清空和结果回填。

1. 在组件管理中添加本目录为本地插件源，安装并启动“示例文本处理”；也可直接选择 `component` 目录安装组件。
2. 打开画布，点击“添加应用”，选择 `application` 目录。
3. 在应用的“组件连接 / 权限”中，为两个能力选择具体实例。“示例文本处理”优先列出，也可选择实现同一能力契约的组件。
4. 输入文字，点击“整理文本”或“词频统计”，在前台权限窗口确认后查看真实处理结果。

安装和连接本身不授权。每个应用有自己的授权主体；重新选择实例会撤销此前应用授权。示例组件允许建立多个独立实例，可用它验证连接不会自动切换。应用目录声明入口和依赖；普通使用无需编辑 JSON。

应用 QML 仅获得 `appCapabilities.call(alias, params, requestId)`，通过 `completed(requestId, resultJson)` / `failed(requestId, message)` 接收结果；`active` 表示当前界面是否可发起调用。平台在切走、关闭、撤权或移除时停用旧请求。原生本机 QML 属于受信任代码，不是文件/网络沙箱。

每个应用的 QtQuick LocalStorage 路径位于其稳定应用身份的 `application-data/<applicationId>/qml-storage` 下，应用自身数据与包快照分开。移除应用清除安装记录、连接和授权，保留应用数据。当前版本不支持应用包就地升级、Python 界面入口或应用事件订阅。

应用依赖通过 `contract` 和 `access` 声明，`label` 是连接界面的显示名称，`preferredComponentType` 只控制推荐顺序。组件操作用 `provides` 发布相同的 `名称@主版本` 契约；本地操作名可以不同。选定后连接固定到具体实例和操作，组件停止、重装或能力版本变化时需要重新检查连接。
