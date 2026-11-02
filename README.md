# Polaris

Polaris v0.1.0.0 是基于 Python、PySide6 / Qt Quick 的本地组件工作台。正式入口使用 `next/polaris_platform`：桌宠打开画布，组件管理负责安装、启动、授权和撤销，业务能力由各组件提供。

## 能力与使用

- 默认鲸鱼娘皮肤复用现有透明动画，支持进入回应、按压、拖放和随机待机；右键打开组件管理或退出。工具窗不接受焦点，身体、气泡和菜单之外的透明区域可穿透输入，实际效果取决于窗口系统。
- 画布挂载组件自己的原生视图，支持移动、缩放、折叠和布局保存。隐藏或移除视图保留业务数据，停止组件才结束其能力。
- 日程组件提供收集箱、我的一天、任务库、周/月计划、完成记录、搜索、子任务、重点、笔记、改期和删除撤销。[日程说明](next/components/schedule/README.md)。
- Agent 组件管理明确标记的 Pi、Codex 会话，显示状态和最终回复，按宿主能力向会话发送新一轮或追加指导。[Agent 说明](next/components/agent/README.md)。
- 微信组件提供扫码绑定、文字收发、可选的 DeepSeek 自动回复，以及明确选择的组件工具调用。密钥从 `DEEPSEEK_API_KEY` 读取。[微信说明](next/components/weixin/README.md)。
- 公开能力按安装身份和具体操作授权；新增能力不自动授权，撤权约束已有视图和调用上下文。后台恢复不重新授予已撤销权限。

首次启动只启用平台和桌面基础组件，业务组件通过组件管理器从 `next/components` 加载，也可选择配置装配；已有安装按保存的自启动设置恢复。开发接口、皮肤动作槽、原生视图授权和验证方法见 [组件平台说明](next/README.md)。

## 运行

Python 3.10+；在仓库根目录建立独立环境：

```bash
python -m venv .venv
# Linux / macOS
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

`python main.py --version` 显示软件版本。`--headless` 打印所选组件状态后退出。`--config PATH` 选择装配，`--state-dir PATH` 指定平台安装与授权数据目录。开发者也可运行 `PYTHONPATH=next python -m polaris_platform --gui --config next/config.schedule.json`；模块入口不加 `--gui` 时只启动、检查并停止所选组件。

平台与业务组件分别维护自己的数据，不将旧版 JSON 自动迁入正式平台。旧代码与文档保留供参考；升级前备份原数据，旧版的 OneDrive 同步、旧桥协议及固定 cell 画布不作为本版本能力。[平台兼容与数据目录](docs/platform-compatibility.md)。

## 打包

在目标操作系统自己的虚拟环境中执行：

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm Polaris.spec
```

输出为 `dist/Polaris/`；Windows 运行 `Polaris.exe`，Linux 运行 `Polaris`。分发时保留整个目录，不能只复制可执行文件。源码和包内默认皮肤均自带动画及许可，不依赖外部素材下载。Windows、macOS 的构建与真实桌面效果仍需分别验收，Linux 构建也不能代替其他系统构建。

冻结包中组件命令的 `{python}` 使用随包解释器，只能使用已随包的 Python 依赖。需要额外依赖的插件应在自己的环境安装依赖，并在组件命令中指定该环境的解释器。

## Agent 插件

Agent 插件需要 Node.js 20+。正式插件位于源码的 `next/integrations`。Pi 使用 `pi install /绝对路径/Polaris/next/integrations`，已有会话执行 `/reload`；Codex 的本地 marketplace 安装和 hook 信任步骤见 [插件接入说明](next/integrations/README.md)。发布包插件目录为 `Polaris/_internal/next/integrations`，组件目录为 `Polaris/_internal/next/components`；安装时使用对应路径。

先启动 Agent 组件，再明确标记会话。插件使用 Agent 自己的本机认证端点；不沿用旧版 `integrations` 插件或中继配置。连接和发送能力取决于宿主支持，未确认的结果显示未知，不重放不确定的发送。

## 组件设计原则

以下是 Polaris 的组件设计约束与演进方向，当前实现仍需逐步对齐。

- **能力归组件所有。** 每个组件负责自身功能、数据、规则和状态，通过公开能力接口协作。使用接口承诺的返回字段属于正常依赖；组件不依赖对方内部实现。
- **能力与展示分开。** 画布本身也是组件，负责呈现与组织。组件可以没有视图，隐藏视图与停止能力是不同操作。
- **协作有明确负责人。** 发起协作的一方负责本次过程的组织、失败处理和结果汇报；各参与组件负责履行自身接口承诺、反馈结果与错误。共同底座提供共同机制，具体业务规则归所属组件维护。
- **依赖与退出行为明确。** 区分可选与必需依赖：可选依赖缺失时只减少相关功能，必需依赖缺失时明确报告相关能力不可用。允许组件动态加入和退出，并明确依赖变化后的行为。
- **能力自动发现，使用范围明确授权。** 能力及权限选项随组件加入、退出而更新，新增能力不自动获得授权。授权来源与范围在调用链中保持明确，不因调用另一个组件而获得它的全部权限。

判断边界是否合理，可以问：

- 对方保持接口契约、更换内部实现时，本组件是否仍需修改？
- 对方退出后，本组件还能做什么？
- 新增组件是否迫使许多旧组件修改？
- 同一业务规则是否由所属组件统一解释和维护？

必要的跨边界输入校验仍可保留，业务含义以所属组件为准。
这些原则借鉴 [KDE Plasma](https://api.kde.org/plasma-containment.html)、[OSGi](https://www.osgi.org/resources/architecture/)
和 [Home Assistant](https://contributors.home-assistant.io/architecture/core/) 的组件与协作思想。

## 版本与许可

软件版本为 **v0.1.0.0**；组件清单版本和协议版本独立维护。[更新记录](CHANGELOG.md)。

代码采用 [MIT](LICENSE)。默认美术素材来自 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，角色原型作者为上善无形，女仆鲸鱼娘设计为 ZipZipPipe，并非 DeepSeek 官方形象。素材遵守 **CC BY-NC-SA 4.0：署名、非商业、相同方式共享**；代码与美术素材分别适用各自许可。完整署名、来源和许可随包保留于 [默认皮肤目录](next/polaris_platform/desktop/skins/dshpet/ATTRIBUTION.md)。
