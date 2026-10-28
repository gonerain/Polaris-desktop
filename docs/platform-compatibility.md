# Windows、Linux 与 WSL 兼容边界

## 当前应用

同一份 Python / QML 源码用于 Windows 和 Linux。资源通过源码或 PyInstaller 的
内部目录定位，数据使用 Qt `QStandardPaths.AppLocalDataLocation`，不硬编码盘符。
Windows 和 Linux 分别使用自己的 Python 虚拟环境、构建缓存和输出目录；不能跨系统打包。

- **Wayland / WSLg**：通过实际 Qt 平台名识别，不根据 `sys.platform == linux` 猜测。
  调整窗口大小，但不设置全局窗口位置、不强制钳制位置，也不对位置做完整态过渡动画。
  拖动、缩放使用 Qt 系统操作；放置、置顶和可用工作区最终由合成器决定。
- **Windows / X11**：保留可用工作区内的位置约束与完整态几何过渡。
  X11 跳过任务栏只是可选提示；库或符号不可用时安全跳过，不影响启动。
- **无托盘 / 原生消息服务**：紧凑态仍显示桌宠提醒气泡，画布及完整态使用临时行内提示。
  提示不抢焦点、不截获点击，不为此增加 Linux 通知守护进程或桌面扩展。
- **字体**：界面使用系统字体回退，不强绑微软雅黑、Segoe UI 等 Windows 字体。
  精简 Linux / WSL 需要安装中文字体，否则会显示方框；字体不是应用自动下载的资源。
- **渲染**：生产启动不设置 `QT_QUICK_BACKEND` 或强制 X11。临时自动化诊断使用
  `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software`，不能据此宣称真实拖动已验证。

## Ubuntu / WSL2 + WSLg 运行

需 WSLg 的图形服务；没有 WSLg 时，offscreen 只能诊断，不能作为正常桌宠运行方式。
Ubuntu 示例依赖（其他发行版使用各自包名）：

```bash
sudo apt-get update
sudo apt-get install python3-venv fonts-noto-cjk \
  libegl1 libopengl0 libxkbcommon0 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xkb1

# 与 Windows 的 .venv 分开，WSL 虚拟环境放 Linux 文件系统。
python3 -m venv ~/.cache/polaris-linux-venv
source ~/.cache/polaris-linux-venv/bin/activate
python -m pip install -r requirements.txt pyinstaller
python main.py

# 不覆盖 Windows 的 build/Polaris 和 dist/Polaris。
python -m PyInstaller --noconfirm --workpath build/linux --distpath dist/linux Polaris.spec
./dist/linux/Polaris/Polaris
```

不要为了 WSL 把 `DISPLAY` 固定成某个 IP，或永久强制 `QT_QPA_PLATFORM=xcb`。
WSLg 的 `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` 应由环境正确提供。
遇到显示服务连接失败先检查运行目录和套接字，不在应用中自动修改用户会话目录的权限。

Linux 数据通常为 `${XDG_DATA_HOME:-$HOME/.local/share}/Polaris/Polaris`；
Windows 通常为 `%LOCALAPPDATA%\Polaris\Polaris`。实际位置以 Qt 返回值为准。
两侧默认独立存储；**不要让两个系统同时编辑同一份任务文件**，不能假设跨系统锁可靠。
迁移数据时先退出两端，备份后复制 JSON。

## Agent 接入与 WSL 中继

Agent 桥和 Pi 插件已实现；安装与协议见 [接入说明](../integrations/README.md) 及 [协议 v1](agent-bridge.md)。传输边界：

1. 同环境使用 Qt LocalSocket：Windows 命名管道，Linux Unix domain socket。
   消息是 UTF-8 JSON Lines；业务协议与 Agent 组件不知道系统类型。
2. **Windows Polaris 与 WSL Agent 需要跨环境连接，不能拿 Linux socket 直接连接 Windows 管道。**
   使用显式启动的宿主侧标准输入/输出中继：WSL 适配器借助 WSL interoperability 启动
   Windows 连接助手，助手通过当前用户的 Windows 管道转发原始消息。
   反向接入可由 Windows 显式启动指定发行版中的 Linux 连接助手。
3. 中继只负责字节传输，不是第二个 Polaris GUI、不承担 Agent 状态或组件业务，
   不经 shell 拼接来自会话的项目路径或命令，不自动猜测发行版、安装位置或宿主 IP。
   Windows interoperability 被禁用时明确报错，不偷偷退回网络监听。
4. 当前程序提供 `--bridge-stdio` 模式，读取宿主端点并为 hello 注入凭证。
   两侧不复制 token；适配器显式选择宿主助手，消息限长、认证和连接级组件授权仍由桥检查。
5. 不为跨 WSL 开放 TCP、共享公网令牌或依赖 NAT / mirrored networking。
   项目路径是源环境中的元数据，不被另一侧直接当作本地文件路径使用。

## 验证口径

WSL 可以验证 Linux Python / Qt、Unix socket 和打包路径，但不等于覆盖所有 Linux 桌面。
Wayland 会话初始化、offscreen 界面诊断、X11 可选库容错与真实桌面鼠标拖动应分别记述。
GNOME / KDE 原生通知、不同合成器的置顶策略、多显示器 / 缩放仍需各自环境验证。
所有诊断使用临时目录或内存存储，不读取实际用户日程，不增加持久测试套件。

本轮已实测（Ubuntu 24.04 / WSL2，Python 3.12，Qt 6.8.3；Windows Python 3.13）：

- Linux / Windows 离屏界面：共享任务模型、UTF-8 存储与备份、完整态往返、
  禁止全局定位时不改变 x/y、原有定位约束、无托盘提醒与焦点保留。
- WSLg 原生 Wayland 的 Qt 会话初始化；真实桌面拖动及合成器置顶策略尚未验收。
- WSL Node ↔ Linux Qt Unix socket 的中文 JSON 往返。
- WSL 进程 → Windows 标准输入/输出助手 → Windows Qt 当前用户命名管道的中文 JSON 往返。
  后续已补充正式 `--bridge-stdio` 的认证、组件调用、会话事件验证，以及 Pi 官方加载器的生命周期回调验证；均使用临时存储，不调用收费模型。
- Linux PyInstaller 成品在独立 XDG 临时目录启动、保持运行并拒绝第二实例。
  WSL 的 `/mnt/c`、`/mnt/d` 文件访问可能较慢，诊断应等待就绪标志，而非固定睡几秒就认定失败。
