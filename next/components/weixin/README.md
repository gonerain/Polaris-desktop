# 微信组件

提供扫码绑定、文字收发、可选的 DeepSeek 自动回复和画布聊天视图。未绑定时启动组件不会联网。点击“扫码绑定”，使用手机微信扫码并确认；如提示配对码，输入手机显示的码继续。

## 运行

在仓库根目录使用现有 Python 环境：

```sh
python -m pip install -r next/components/weixin/requirements.txt
PYTHONPATH=next python -m polaris_platform --gui --config next/config.weixin.json
```

也可通过组件管理器加载 `next/components/weixin` 并启动，再在画布选择“微信”，确认权限后挂载。图形界面需要 PySide6，二维码本地绘制需要 `qrcode`。关闭或移除视图保留通信，停止组件结束通信。

绑定者先发一条文字消息后，本机可以回复，每条最多 2000 字。发送未确认时显示“发送结果未知”，不会自动重发；可在手机微信核实结果。

## 自动回复

在启动组件的进程环境中设置 `DEEPSEEK_API_KEY`，重启组件后，在聊天顶部打开“自动回复”。密钥只从环境读取，界面仅显示是否缺失，不提供密钥输入或保存。自动回复默认关闭；启用后处理新收到的文字，调用 DeepSeek，并将回复发回微信。模型请求在后台线程执行，顶部显示处理中或错误。

“设置”中按组件和操作勾选模型允许调用的公开操作，标注读取或写入；点击“保存”生效。打开设置才读取目录，关闭设置保留未保存的勾选。“新对话”清除本机模型对话历史。允许列表保存在本机，重启后保留，但自动回复需重新手动启用，以使用此次打开视图的真实调用上下文。发送给 DeepSeek 的内容包括新收到的文字及工具结果。

本地允许列表与平台授权同时约束工具调用。在“组件管理”顶部的“权限使用者”选择实际打开微信视图的调用来源（通过画布打开时为画布组件），在目标组件的“能力与权限”给相应操作授予“本机交互”权限；公开目录还需要 `collaboration` 的 `discover`、`describe` 权限。微信视图自身需要 `get`、`agent_settings`、`agent_catalog` 读取权限及 `configure_agent`、`new_conversation` 写入权限，挂载时按提示授权。工具沿用这个调用来源和上下文，并无独立微信授权身份；未获平台授权的操作即使勾选也不能执行。撤销读取后在下次授权复验时清除视图缓存，写入在每次提交时重新检查授权。

## 能力接口

`get` 返回状态、提示、账号标识、二维码内容、发送状态及最近消息；每条消息包含 `id`、`text`、`direction`、`status`、`time`。

写操作为 `login`、`verify(code)`、`connect`、`disconnect`、`logout`、`send(text)`、`clear_messages`。`main` 视图使用通用 `qt-quick-item` 契约，通过 `create_view` / `release_view` 创建与释放。`agent_settings` 返回自动回复状态、密钥是否存在和允许列表；`agent_catalog` 返回公开操作元数据；`configure_agent(enabled, allowed)` 设置本轮启用状态和可选允许列表；`new_conversation` 清除本机模型历史。业务接口不依赖 Qt。撤销读取权限后视图清除账号和消息展示；写入操作也会重新校验授权。

## 本地数据

默认数据目录：Windows 为 `%LOCALAPPDATA%/polaris-weixin`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/polaris-weixin`；入口支持 `data_dir` 指定独立目录。

Windows 使用 DPAPI 加密保存 `credentials.bin`；Linux 使用本地 JSON 保存 `credentials.bin`，以 `0600` 文件权限限制为当前用户读写，不加密。保存内容包括账号凭证、绑定标识、接收进度和最近 512 条消息的去重标识，不保存会话 context token 或临时二维码。重启后恢复绑定和聊天记录，点击“连接”继续接收，无需再次扫码；保存失败会显示提示。损坏、过大或版本不支持的凭证文件会保留，退出绑定后可重新保存。`chats/` 内为按账号及绑定用户隔离的 JSON 聊天记录，每组最多保留最近 100 条。清除消息删除当前记录；退出绑定清除当前账号凭证和聊天记录。

自动测试使用临时目录、虚构账号和假网络，不会发送真实微信消息；界面测试在独立 Qt 子进程中运行，未安装 PySide6 时跳过。
