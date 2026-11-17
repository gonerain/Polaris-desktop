# 日程应用

独立应用 `org.polaris.schedule-app`，基于日程组件的公开能力。所有任务、Google 授权和事件同步由所连接的日程组件管理；应用只负责规划、展示和编辑，不复制数据存储或同步服务。

## 布局与交互

- 左侧：迷你月历、我的一天、收集箱、待重新安排、已完成、日历显示开关和待安排任务。
- 顶部单一工具栏：日期导航、日／周／月／每日计划、“显示完成”、新任务和搜索；窄窗将视图切换折叠为下拉菜单。主区直接显示日历或计划，不另设视图工具行和长条添加栏。Google 事件按起止时间显示，重叠事件分列，全天／跨天事件覆盖相应日期；时间以本机时区显示。
- 详情：宽窗使用右侧面板，窄窗使用弹层。可创建任务、修改日期和钟点、完成状态、重点、笔记，新增／完成／删除子任务；任务删除需确认并可撤销。未保存的草稿切换或关闭前会确认，保存失败保留输入。
- 从收集箱任务右侧把手拖到日／周时间格，以 30 分钟为单位安排钟点；拖到全天区清空钟点，拖到月历日期保留原钟点。双击空白时间格创建任务。
- 统一使用顶部“新任务”或双击时间格创建任务；`Ctrl+N` 新任务、`Ctrl+F` 搜索、`Ctrl+Z` 撤销删除。可切换深浅主题。

任务的钟点只是安排时刻，不代表截止时间或持续时长。时间网格中的任务使用紧凑标记，不向组件添加虚构的结束时间。Google 事件在本应用中只读，详情可跳转 Google Calendar。

日历开关只改变应用显示；Google 设置中的“同步的日历”决定日程组件读取哪些日历。已连接的 Google 账号无需重复授权。通过日程组件读取其现有的过去 90 天至未来一年缓存和同步状态。

## 安装、连接与授权

在应用管理安装本目录，或从市场安装“日程”应用。启动 `org.polaris.schedule`，在应用的“组件连接 / 权限”中将各能力连接到同一个日程实例，然后打开应用。首次读取或写入由平台确认权限；不自动授予权限，不直接访问组件的文件或内部对象。

需要 `get`、任务的 `add/update/delete/undo_delete/add_subtask/update_subtask/delete_subtask`，以及 Google 的 `google_connect/google_cancel/google_select/google_sync/google_disconnect`。契约为 `polaris.schedule.<操作的短横线名称>@1`。日程组件从 `0.2.1` 起明确提供稳定实例应用绑定。

应用显示期间每 15 秒读取日程快照，操作成功后立即刷新；组件的 Google 网络同步仍由其自身执行。读取失败明确显示错误并暂停自动读取，用户可点击“重新读取”。权限确认等待不设总时限。关闭应用不停止所连接的日程组件。

## 设计参考

交互参考 [Google Calendar](https://calendar.google.com/) 的日期导航、日／周时间网格和全天事件，以及 [Super Productivity](https://github.com/super-productivity/super-productivity) 的收集箱、每日规划和任务详情。界面与布局代码为本项目自己的 Qt Quick 实现。

## 验证

从仓库根目录运行（需要 PySide6）：

```sh
TZ=Asia/Shanghai QT_QPA_PLATFORM=offscreen PYTHONPATH=next:marketplace/packages/schedule python -m unittest discover -s marketplace/packages/schedule-app/tests -v
```

覆盖日周月计划、全天排他结束日期、事件重叠分列、任务增改删撤销、真实鼠标拖放、子任务、搜索和日历开关、草稿保存失败、窄窗详情和能力契约。
