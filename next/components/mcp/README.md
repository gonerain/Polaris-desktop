# MCP 接入

MCP 接入组件为本机 Codex 等 MCP 客户端提供北极星组件调用。北极星运行时提供授权和路由，MCP 组件负责工具目录、参数说明和 JSON 结果转换。

桌面默认安装并启动。`polaris_components` 列出当前可调用的组件；`polaris_help(component, operation?)` 查询公开说明；`polaris_call(component, operation, arguments?)` 执行操作。组件使用完整 ID 定位。目录和权限在每次调用前刷新，组件停止、操作撤回和撤权立即影响后续调用。

此目录也可独立部署：复制目录后用 `standalone-manifest.json` 替换部署副本的 `manifest.json`，入口为 `polaris_mcp:create`。需要由可信装配配置 `trustedBindings=true`，为工厂注入 `runtime`；普通目录加载不能取得该绑定。旧版平台支持这一公开装配契约时，可安装独立组件而无需覆盖平台程序。随平台发行的 `manifest.json` 使用包内入口 `components.mcp:create`。

默认 `default_all=true`，为新发现的可调用公开操作和事件授予后台权限，包含读和写。默认决策按 MCP 安装身份、目标安装身份及具体能力语义保存；已处理的权限不会因重启、轮询或调用而补授，管理界面撤销后台权限后持续生效。新安装或新能力按默认策略首次授权。可信装配可设置工厂参数 `default_all=false`，此时仅使用已有明确后台授权。Qt 原生对象接口、`humanOnly` 和 `modelCallable=false` 操作不作为模型工具提供。

组件通过同用户私有端点文件连接仅绑定 `127.0.0.1` 的服务，使用每次启动轮换的随机认证令牌；端点不包含聊天身份，不依赖某个 Codex 会话。停止组件会关闭服务并删除端点。数据默认位于平台分配的组件目录；无持久化平台目录时仅使用临时数据。

## 连接 Codex

Linux 安装包示例：

```bash
codex mcp add polaris -- /opt/polaris/Polaris --component-python /opt/polaris/_internal/components/mcp/stdio.py
```

源码示例（将路径替换为实际位置）：

```bash
codex mcp add polaris -- /path/Polaris/.venv/bin/python /path/Polaris/next/components/mcp/stdio.py
```

默认从当前用户的 `polaris-platform/installations.json` 定位 MCP 安装端点；使用自定义 `--state-dir` 的北极星实例时，为 stdio 脚本显式添加 `--endpoint /path/to/component/endpoint.json`。可在组件 `status` 操作中查询端点位置。客户端启动 stdio 脚本，不启动另一份北极星。连接配置在支持 MCP 重载或重新打开的 Codex 聊天中生效。

支持 MCP `initialize`、初始化通知、`ping`、`tools/list` 和 `tools/call`，协商版本为 `2024-11-05` 至 `2025-11-25`。未知方法返回 JSON-RPC 错误。工具执行错误返回 `isError=true`。不提供事件订阅工具、主动通知或离线调用。每帧最多 1 MiB；大结果应由业务操作的范围参数缩小。连接失败或结果未知时不自动重试写操作。

组件是可信本机输入边界，仅由可信装配注入 Runtime；普通目录插件不能自行申请该控制绑定。业务调用仍经过普通 Client 和平台实时权限检查，不提供安装、授予权限等管理后门。

验证：`PYTHONPATH=next .venv/bin/python -m unittest next.tests.test_mcp -v`。
