# 平台兼容与数据目录

Polaris v0.1.0.0 的正式入口是仓库根目录 `main.py`，实现位于 `next/polaris_platform`。Python 3.10+，桌面使用 PySide6 / Qt Quick。Windows、Linux、macOS 各自使用本机虚拟环境和构建输出；PyInstaller 不能跨系统生成可执行文件。

## 运行与构建

Linux / WSLg 示例：

```bash
python3 -m venv ~/.cache/polaris-linux-venv
source ~/.cache/polaris-linux-venv/bin/activate
python -m pip install -r requirements.txt pyinstaller
python main.py
python -m PyInstaller --noconfirm --workpath build/linux --distpath dist/linux Polaris.spec
./dist/linux/Polaris/Polaris
```

Ubuntu 精简环境可能需要 `python3-venv`、`fonts-noto-cjk`、`libegl1`、`libopengl0`、`libxkbcommon0` 及所选 Qt 平台插件依赖的 XCB 库。使用发行版包管理器安装缺失库；应用不会下载字体或修改图形会话配置。Windows 使用自己的 Python 环境执行同一份 `Polaris.spec`，成品保留整个 `dist/Polaris` 目录。

`main.py` 默认启动图形界面，`--gui` 可显式指定；`--headless` 只启动所选组件、打印状态后退出。`--version` 不启动 Qt。模块入口 `python -m polaris_platform` 仍默认无界面，需 `--gui` 才进入桌面。

## 窗口系统边界

桌宠使用 Qt 工具窗和不接受焦点标志；输入区域由皮肤、气泡和菜单的几何区域组合，透明空白由原生窗口 mask 让出。未配置输入区域的普通视图保留矩形窗口行为。部分平台同时用 mask 裁剪显示，皮肤须覆盖所有可见动画。

- **X11**：隔离 X11 的真实鼠标测试已覆盖焦点保持、空白穿透、菜单和气泡区域变化；GNOME 窗口属性检查覆盖工具窗、任务栏/分页器跳过和不接受焦点。
- **Wayland / WSLg**：窗口位置、置顶和输入区域的实际效果受合成器控制，不能按 X11 测试结果推定。不要永久强制 `QT_QPA_PLATFORM=xcb` 或固定 `DISPLAY`。
- **Windows / macOS**：当前版本未做完整实机验收。macOS 的应用级 Dock / Cmd+Tab 不会因为单个工具窗自动隐藏；工具窗失活仍显示依赖 Qt Cocoa 属性，需对应环境验证。
- **离屏**：`QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software` 用于测试和截图，不能证明真实任务切换、穿透或多显示器行为。正常启动不强制这些变量。

## 数据位置

图形入口默认将平台安装身份、组件目录、自启动设置和授权保存到：

| 系统 | 平台数据目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%/polaris-platform`；未设变量时按当前实现回退到用户主目录下 `.local/share/polaris-platform` |
| Linux / macOS | `$XDG_DATA_HOME/polaris-platform`；未设变量时为 `~/.local/share/polaris-platform` |

`--state-dir PATH` 指定平台目录。桌宠位置和画布布局保存在平台的对应组件数据目录。无界面入口默认仅用内存，显式指定 `--state-dir` 才持久化。既有平台安装可继续使用同一目录；撤销授权和卸载记录跨重启保留。备份时退出应用并复制平台数据目录。

## 验证

验收分别记录单元测试、Qt 离屏测试、隔离 X11 测试、目标系统打包和真实桌面验证。测试使用内存或临时目录。

```bash
PYTHONPATH=next .venv/bin/python -m unittest discover -s next/tests -v
.venv/bin/python main.py --version
.venv/bin/python main.py --headless
```
