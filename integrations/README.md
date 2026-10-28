# Polaris Agent 接入

这个目录是可安装的 Pi 本地包，也包含不依赖 Pi 的 Node 客户端 `client.mjs`。
其他 Agent 可以使用客户端或直接遵守 [本机协议](../docs/agent-bridge.md)，无需修改 Polaris 核心。
目前已实现 Pi 适配器，未实现 Codex 适配器。Pi 接入按本机 1.4.0 Extension API 验证，需支持 `agent_settled` 生命周期事件。

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
