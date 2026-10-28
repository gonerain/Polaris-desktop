# Polaris Agent 接入

这个目录是可安装的 Pi 本地包，也包含不依赖 Pi 的 Node 客户端 `client.mjs`。
其他 Agent 可以使用客户端或直接遵守 [本机协议](../docs/agent-bridge.md)，无需修改 Polaris 核心。
`tools.json` 是 Pi、Codex MCP 与内置微信 Agent 共用的工具参数契约，安装或复制插件时须保留此文件。
已实现 Pi 适配器及 Codex 桌面本地插件。Pi 接入按本机 1.4.0 Extension API 验证，需支持 `agent_settled` 生命周期事件。

## Codex 桌面本地插件

本目录同时是 Codex 插件根目录；`.codex-plugin/plugin.json`、`.mcp.json` 与 `codex/` 必须一起安装，
不可只复制 `codex/`。需要宿主环境 PATH 中可用的 Node.js 20+（Windows 已用 Node 24 验证），不需要 npm install 或 API key。

仓库自带 `.claude-plugin/marketplace.json`，来源为 `Polaris Local`，插件名为 `polaris`。
用 Codex 桌面打开这个 worktree，重启应用后到插件目录选择此来源并安装、启用 Polaris；
审阅并信任插件的 hooks，再打开新会话。安装本身不等于信任 hooks，不应绕过信任检查。
本机 PATH 中的旧 `codex-cli 0.31.0` 没有插件管理命令，不能用它验证桌面插件加载。
官方配置及信任规则见 [插件打包](https://developers.openai.com/plugins/build/plugins) 与 [Hooks](https://learn.chatgpt.com/docs/hooks)。

先启动 Polaris。`SessionStart / UserPromptSubmit / Stop / Interrupt / SessionEnd` 通过命令 hook
把少量元数据交给每会话的本机助手，由助手保持到 Polaris 的连接。无需模型调用工具，也不轮询会话、扫描进程或解析聊天文件。
仅连接心跳和故障重连使用定时器。可沿用下文 `POLARIS_ENDPOINT / POLARIS_RELAY`；环境变量必须由 Codex 宿主继承。

**结束语义有限制：Codex 没有这里可用的 Pi `agent_settled` 等价事件。**
`Stop` 是一次停止尝试，其他 hook 仍可要求继续；此插件在 Stop 上报 `unknown`，会触发 Polaris 的现有结束气泡，
不保证是最终静止状态或任务成功。同一 turn 的重复 Stop 只提醒一次。要求严格最终结束时，不应把这个提示当作最终确认。
`Interrupt` 上报 `cancelled`，未匹配当前 turn 的结束事件忽略；没有可靠失败字段时不猜测 failed。
hooks 不提供原生会话标题，列表及气泡使用 `Codex · 项目名 · 会话短ID`，不读取提示词来推断标题。
不监听子代理事件，避免把子代理结束误当主会话结束；压缩 SessionStart 保留正在运行的状态。

每个会话助手占一个桥连接；三个组件工具另占一个独立连接，名称为 `Codex tools`，
在 Polaris 的 Agent 完整视图里为这个工具连接按组件授权。工具与 Pi 一样为
`polaris_components / polaris_help / polaris_call`；默认拒绝数据访问，不自动重试写入。
因此还受核心最多32连接的总量限制。MCP 不可用不影响已经启动的 hooks 助手。

SessionEnd 正常注销；异常退出不冒充完成。35分钟没有新的 hook 时助手释放连接，
防止 Codex 崩溃后无限残留；超长无事件运行可能暂时显示断连，下次 UserPromptSubmit 会重建。
Polaris 重启时助手只发送当前快照，不补发离线 Stop。插件禁用不会终止已经存在的助手，
应先关闭相应会话，或等待空闲释放。Windows 命名管道链路已验证；Linux/WSL 的实际 Codex 宿主加载尚未验收。

验证使用临时端点与内存数据：覆盖真实 Qt LocalBridge/AgentHub 认证、会话开始、Stop 去重、取消、注销，
以及 Node 管道重连、MCP 初始化、工具发现/调用、权限拒绝与参数校验。未调用收费模型、未接触真实日程。
真实 Codex 桌面的安装、hook 信任及宿主事件触发仍需在安装后验收。

## Pi：Windows / Linux 同环境

先运行 Polaris，然后在各自系统的 Pi 中安装：

```text
pi install PATH_TO_POLARIS/integrations
```

发布包中目录为 `Polaris/_internal/integrations`。不必安装新 npm 依赖，Pi 提供宿主包。
只试用一次可运行 `pi -e PATH_TO_POLARIS/integrations/pi/polaris.ts`。
已有会话安装后执行 `/reload`，新会话自动加载；未加载插件的旧会话不会被扫描出来。

- 每轮结束后，桌宠自动弹出「会话标题」的会话结束了；**不需要模型调用工具或授权桌宠组件**。
  Pi 使用 `agent_settled`，不是中途可能继续执行的 `agent_end`。断线不提醒，重复事件只提醒一次。
- `/polaris`：查看连接状态；`/polaris connect` 可立即再试连接。
- `polaris_components`：发现组件；`polaris_help`：查询用法；`polaris_call`：按 help 调用。
- 在 Polaris 画布的 Agent 面板点击 `↗`，按连接和组件授予只读或修改权限。默认拒绝数据访问。
  断线重连和 reload 后授权清空；不会自动把日程加入模型上下文。

### 可选：主动让桌宠发言（不是结束提醒所必需）

先在 Agent 面板的 `↗` 完整视图中为当前连接的“桌宠”选择“允许修改”，再查询 `polaris_help({component:"pet"})`，
使用 `polaris_call({component:"pet",operation:"say",args:{text:"Hi！👋",durationMs:6500}})`。
紧凑状态在桌宠旁弹泡泡；画布展开时显示界面内短提示，不切页、不抢焦点。
新消息替换旧消息，1000..15000毫秒后消失。只支持短消息，不播放语音、不自动转发聊天全文。
右键桌宠的“打个招呼”也能直接试用，无须外部连接授权。

默认寻找当前系统用户数据目录下的 `Polaris/Polaris/bridge/endpoint.json`。
使用 `POLARIS_ENDPOINT` 可显式指定同一环境中的私有端点文件；不要把密钥复制到仓库。

## WSL Pi → Windows Polaris

Linux socket 不能直接连接 Windows 命名管道，使用宿主助手。以当前仓库路径为例：

```bash
export POLARIS_RELAY='["/mnt/d/Code/Polaris/Polaris-desktop/dist/Polaris/Polaris.exe","--bridge-stdio"]'
pi
```

将路径改成你实际安装位置；参数必须是 JSON 数组，不是 shell 命令字符串。
Windows 助手读取 Windows 用户的端点并注入认证密钥，不需要 WSL 读取 Windows token 文件。
这是本机标准输入/输出转发，不开放端口，不依赖 WSL NAT 或 mirrored networking。
从源代码启动宿主助手也可以：

```bash
export POLARIS_RELAY='["/mnt/d/Code/Polaris/Polaris-desktop/.venv/Scripts/python.exe","D:/Code/Polaris/Polaris-desktop/main.py","--bridge-stdio"]'
```

Windows Pi → WSL Polaris 可显式指定对应发行版及 Linux 成品路径：

```powershell
$env:POLARIS_RELAY = '["wsl.exe","-d","Ubuntu","--","/home/YOU/Polaris/Polaris","--bridge-stdio"]'
pi
```

不会自动启动另一个 GUI。宿主 Polaris 必须已运行，WSL interoperability 必须可用。
有意配置的 relay 优先于本系统端点；禁用中继时移除 `POLARIS_RELAY`。
若 `POLARIS_ENDPOINT` 指向自定义位置，中继需通过自己的 `--endpoint HOST_PATH` 参数指定，
Linux 路径不能直接当作 Windows 路径传入。

## 其他 Agent 的最小 Node 用法

```javascript
import { BridgeClient } from './client.mjs';
const client = new BridgeClient({ name: 'My Agent' });
client.on('connected', () => {
  client.event('session.snapshot', {
    sessionId: 'session-1', source: 'My Agent', name: 'Example',
    project: '/source/project', state: 'idle'
  });
});
client.start();
// 确认 connected 后：
// client.event('run.started', { sessionId: 'session-1', runId: 'unique-run-1' });
// client.event('run.ended', { sessionId: 'session-1', runId: 'unique-run-1', outcome: 'ended' });
// 退出前 session.removed，然后 client.stop()。
```

跨 WSL 客户端传入 `{ name, relay: [可执行文件, ...参数] }`。
不要上传提示词或回复全文，不要用运行结束替代任务成功；离线事件不补发。
组件写请求超时、断连或 `applied=true` 时都不能盲目重试，先查询实际结果。

## 回归检查

在仓库根目录运行（Windows 将 Python 换成 `.venv\Scripts\python.exe`）：

```text
python -m unittest discover -s tests -v
node --test tests/integrations.test.mjs
```

Python 检查使用假网络、临时文件和离屏 QML；Node 检查使用临时本机端点与内存日程，
验证真实 Qt 桥认证、权限拒绝、MCP 参数契约及 Codex 会话事件。Node 的 Qt 桥检查需要允许创建本机套接字/命名管道，
默认使用仓库 `.venv`，可用 `POLARIS_TEST_PYTHON` 指定已安装项目依赖的解释器。均不调用收费模型或真实微信。
