# Polaris

轻量桌宠式悬浮日程，Python + PySide6 / Qt Quick。点击鲸鱼娘打开日程，右键或托盘菜单退出。

- 当前使用 dsh-pet 女仆鲸鱼娘：呼吸待机、挥手、哈欠/睡眠、惊醒、悬空拖动、庆祝，以及伸懒腰、玩魔方、东张西望；右键可换个小动作、休息或减少动态，不加养成系统。
- 紧凑面板默认“我的一天”，支持任务、时间、子任务、完成勾选，以及按需查看月历。
- `↗` 打开任务工作台：我的一天、任务库、周/月计划和完成记录；紧凑任务行、按需详情、全局搜索和点选改期。
- 收集箱可先记录、不选日期；我的一天支持重点星标和拖动排序，详情里按需写下一步笔记。
- 日终整理逐项选择保留、明天或放回收集箱，不自动顺延；顺序、重点、笔记都保存在本地。
- 参考 Super Productivity 的任务优先工作流：先收集，再主动选择今天的事；旧安排单独整理，不自动堆进今日清单。
- 过期待办可以单项或全部移到今天，已完成任务默认收起。
- 自动保存、上个版本备份、损坏保护、主任务删除撤销和单实例锁。
- 组件支持画布态与独立完整态，以及连续展开 / 返回动画。

## Windows 运行与打包

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm Polaris.spec
```

成品为 `dist/Polaris/Polaris.exe`，分发需保留整个 `Polaris` 目录。数据与备份写入用户目录，不写入程序安装目录。

参见 [组件协议](docs/component-board.md) 和 [日程设计、存储恢复及已知边界](docs/schedule-design.md)。当前没有云同步、重复任务或程序关闭后的后台提醒。

## 素材与非商业使用限制

当前动画选自 **[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)**。上游动画素材允许开源使用、**禁止商用**，角色及本包转换后的素材遵守 **CC BY-NC-SA 4.0（署名、非商业、相同方式共享）**。角色原型作者为上善无形，女仆鲸鱼娘设计为 ZipZipPipe；不是 DeepSeek 官方形象。

**不能将包含这套素材的发布包直接用于收费、广告变现等商业用途。** 商用前须更换为已获适当授权的素材，或另行取得完整授权。代码 MIT 不等于美术素材 MIT；素材限制不自动给整个代码库更换许可。

署名、固定来源、修改记录及许可随发布包附于 [assets/dsh-pet/ATTRIBUTION.md](assets/dsh-pet/ATTRIBUTION.md)。[桌宠设计](docs/pet-design.md) 说明动作与性能边界；`tools/import_dsh_pet.py` 可从固定提交的原始透明视频重建素材，FFmpeg 仅构建时需要。

此前 Er1c0v0 的素材与许可保留在 `assets/whale/`，当前不启用，也不随新发布包打包。
