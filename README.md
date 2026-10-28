# Polaris

轻量桌宠式悬浮日程，Python + PySide6 / Qt Quick。点击鲸鱼打开日程，右键或托盘菜单退出。

- 紧凑面板默认今天待办，支持任务、时间、子任务、完成勾选，以及按需查看月历。
- `↗` 打开完整态：待办清单 / 周日程 / 月日程，详情按需展开，支持搜索和点选日期改期。
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

鲸鱼娘悬浮素材来自 [Er1c0v0/dsh-whale-pet](https://github.com/Er1c0v0/dsh-whale-pet)，采用 CC BY 4.0 授权，详见 `assets/whale/ATTRIBUTION.md`。
