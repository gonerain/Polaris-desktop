# Polaris

轻量桌宠式悬浮组件工作台，Python + PySide6 / Qt Quick。点击鲸鱼娘打开平铺画布，日程和 Agent 共用 cell 分配器，右键或托盘菜单退出。

- 当前使用 dsh-pet 女仆鲸鱼娘：呼吸待机、挥手、哈欠/睡眠、惊醒、悬空拖动、庆祝，以及伸懒腰、玩魔方、东张西望；右键可换个小动作、休息或减少动态，不加养成系统。
- 通用 Agent 单格面板展示已接入的活跃会话和本轮结束提醒；Pi 通过薄插件接入，来源不限 Pi，断连不冒充完成。
- 组件通过发现 → help → 调用提供自身能力；外部访问默认拒绝，按连接和组件授权，不自动上传日程或会话全文。
- 日程画布默认“我的一天”，支持任务、时间、子任务、完成勾选，以及按需查看月历。
- `↗` 打开任务工作台：我的一天、任务库、周/月计划和完成记录；紧凑任务行、按需详情、全局搜索和点选改期。
- 收集箱可先记录、不选日期；我的一天支持重点星标和拖动排序，详情里按需写下一步笔记。
- 日终整理逐项选择保留、明天或放回收集箱，不自动顺延；顺序、重点、笔记都保存在本地。
- 参考 Super Productivity 的任务优先工作流：先收集，再主动选择今天的事；旧安排单独整理，不自动堆进今日清单。
- 过期待办可以单项或全部移到今天，已完成任务默认收起。
- 自动保存、上个版本备份、损坏保护、主任务删除撤销和单实例锁。
- 组件支持画布态与独立完整态，以及连续展开 / 返回动画。
- 默认 2×2 画布：日程申请两个 cell，Agent 和微信各申请一个；不加顶栏分页。
- 微信 ClawBot 内置极简 DeepSeek Agent，默认以可配置的鲸鱼娘人设自动回复；通过独立读取授权与按请求的操作计划调用 Polaris 组件。仅新增任务和子任务的首份计划默认自动执行，其余计划通过本机或微信一次性审批。本机保存开关、最近聊天与有限上下文，Key 只读 `DEEPSEEK_API_KEY`，不依赖 OpenClaw。[微信组件说明](docs/weixin-component.md)。
- 浅灰背景负责移动整个画布，边缘调整尺寸，右上角 `− / 百分比 / +` 整体缩放；100%默认窗口552×728。[画布操作说明](docs/canvas-controls.md)。
- 抓组件最上方标题条沿横向或纵向短拖即实时换位；两格日程也可与一整行的单格组件交换，不自由漂移、不斜向移动、不越出画布。`−/+` 最小化/恢复，不释放 cell、不丢草稿。布局暂不跨重启保存。
- 画布和弹层首次使用时创建；业务模型始终保留，已打开的界面也保留实例，不因收起丢失草稿。[资源测量说明](docs/performance.md)。

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

## Pi 插件

先打开 Polaris，再运行 `pi install PATH_TO_POLARIS/integrations`；发布包的插件目录为 `Polaris/_internal/integrations`。已有 Pi 会话执行 `/reload`，新会话自动接入。通过 `/polaris` 检查连接，在 Agent 面板的 `↗` 完整视图中授权组件访问。

提供 `polaris_components / polaris_help / polaris_call` 三个通用工具，不内置日程工具或 Codex 分支。安装、WSL 中继与其他 Agent 接入见 [接入说明](integrations/README.md) 和 [协议 v1](docs/agent-bridge.md)。

## Codex 插件

仓库带 `Polaris Local` 本地插件目录，安装 `polaris` 并审阅、信任 hooks 后，可通过生命周期事件自动接入；
也提供相同的三个组件工具。`Stop` 可能被其他 hook 继续执行，因此这里只上报“结果未知”，不能保证最终结束。
安装、Node 环境与验证范围见 [Codex 接入说明](integrations/README.md#codex-桌面本地插件)。

## Windows 运行与打包

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm Polaris.spec
```

成品为 `dist/Polaris/Polaris.exe`，分发需保留整个 `Polaris` 目录。数据与备份写入用户目录，不写入程序安装目录。

## Linux / WSL

同一份源码支持 Linux 环境，使用独立的 Linux 虚拟环境；不要复用 Windows `.venv`。Ubuntu / WSLg 的中文字体、Qt 系统库、运行及独立打包命令见 [平台兼容说明](docs/platform-compatibility.md)。Wayland 下由合成器控制窗口位置；无托盘时仍保留界面内提醒。

Windows 与 WSL 的 Agent 接入通过显式 `--bridge-stdio` 本机中继连接，不假定两侧共享套接字，也不开放 TCP 端口。使用 `POLARIS_RELAY` 配置命令参数数组，见 [接入说明](integrations/README.md)。

参见 [组件协议](docs/component-board.md) 和 [日程设计、存储恢复及已知边界](docs/schedule-design.md)。当前没有云同步、重复任务或程序关闭后的后台提醒。

## 素材与非商业使用限制

当前动画选自 **[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)**。上游动画素材允许开源使用、**禁止商用**，角色及本包转换后的素材遵守 **CC BY-NC-SA 4.0（署名、非商业、相同方式共享）**。角色原型作者为上善无形，女仆鲸鱼娘设计为 ZipZipPipe；不是 DeepSeek 官方形象。

**不能将包含这套素材的发布包直接用于收费、广告变现等商业用途。** 商用前须更换为已获适当授权的素材，或另行取得完整授权。代码 MIT 不等于美术素材 MIT；素材限制不自动给整个代码库更换许可。

署名、固定来源、修改记录及许可随发布包附于 [assets/dsh-pet/ATTRIBUTION.md](assets/dsh-pet/ATTRIBUTION.md)。[桌宠设计](docs/pet-design.md) 说明动作与性能边界；`tools/import_dsh_pet.py` 可从固定提交的原始透明视频重建素材，FFmpeg 仅构建时需要。

此前 Er1c0v0 的素材与许可保留在 `assets/whale/`，当前不启用，也不随新发布包打包。
