# 日程组件

独立的本地任务组件，组件 ID 为 `org.polaris.schedule`。业务在无界面时即可使用；`main` 视图通过公开的 `qt-quick-item` 契约呈现。

## 启动与装配

安装兼容的 Polaris 平台 SDK 后，可从本仓库根目录使用公开模块入口启动：

```sh
python -m polaris_platform --gui --config config.schedule.json
```

也可在组件管理中添加本仓库为插件源，安装并启动“日程”，再从画布添加日程视图。视图申请 `get`、`time_context` 读取权限及实际使用的写入权限；已显示的视图仍受撤权限制。

`create_view(view="main", parent=QQuickItem)` 返回 `{handle, item}`；`release_view(handle)` 只释放视图。隐藏、移除视图不停止日程业务，重新打开可读取已保存内容。停止组件会释放其全部视图。

## 本地数据

默认保存在 Windows 的 `%LOCALAPPDATA%/polaris-schedule`，或 Linux 的 `$XDG_DATA_HOME/polaris-schedule`（未设置时为 `~/.local/share/polaris-schedule`）。`schedule.json` 保存任务，并保留备份和损坏恢复信息。工厂参数 `data_dir` 可显式覆盖目录，例如在 manifest 的 `entry.kwargs` 中设置绝对路径。保存失败会明确显示错误，界面保留尚未提交的输入。

## 能力接口

所有能力均为 revision 1；读取为 `read`，变更为 `write`。无需获取视图即可调用：

- `get()` 返回 `{tasks, canUndo, storageNotice, timeContext}`；任务包含 `id/title/date/time/done/important/notes/subtasks`。
- `time_context()` 返回 `{now, date, timezone: {name, utcOffsetMinutes}}`，无需读取任务即可获得当前时间。
- `tasks(date?, query="", include_done=true)` 查询任务。`date=null` 仅查询收集箱；省略日期查询全部任务。
- `add(title, date=null, time="", notes="", important=false)` 新增任务，返回任务对象。
- `update(identity, ...fields)` 修改任务字段；`date=null` 放回收集箱。
- `delete(identity)` 删除主任务；`undo_delete()` 恢复最近删除的主任务。
- `add_subtask(identity, title)`；`update_subtask(parent_id, subtask_id, ...fields)`；`delete_subtask(parent_id, subtask_id)` 管理子任务。子任务字段为 `title/done/notes`。
- `reorder(ids, date?)` 调整任务顺序。
- `move_overdue(target_date, today?)` 将过期未完成任务移到目标日期。
- `organize_day(date, changes)` 按 `[{id, ...fields}]` 批量整理指定日期的任务；由用户选择保留、改期或放回收集箱。

主任务支持收集箱、日期与时间、重点、完成、笔记、子任务、改期和删除撤销。界面提供我的一天、任务库、周/月计划、完成记录和搜索。日期格式为 `YYYY-MM-DD`，时间为 `HH:MM` 或空字符串。

`describe()` 为业务操作提供 `title`、`description` 和 JSON Schema `parameters`，包括必填字段、可修改字段及默认行为。任务的 `id` 在修改主任务时使用参数名 `identity`；修改子任务使用 `parent_id` 和 `subtask_id`。

## 时间语义

组件内部的 `LocalClock` 每次从系统本地时间采样。`now` 是带 UTC 偏移的 ISO 时间，`date` 和 `timezone` 从同一次采样生成；`timezone.name` 是系统名称或缩写，不保证为 IANA 标识。组件不缓存时区或当天日期。Python 调用方可通过 `Schedule(clock=...)` 或 `ScheduleStore(clock=...)` 注入实现 `context()` 的时钟；继承 `LocalClock` 时只需覆盖返回带时区 datetime 的 `now()`。

界面每秒通过 `time_context()` 刷新时间，重新显示时立即刷新。跨天时，正在查看今天会跟随到新的一天，浏览其他日期则保留所选日期；“今天”和“明天”按钮也使用日程时钟。恢复休眠后的下一次采样读取实际时间，不累计计时推算日期。

任务的 `time` 是安排钟点，不是截止时间，也不触发提醒。“待重新安排”和 `move_overdue()` 仅按日期判断未完成任务；`move_overdue(today=...)` 可指定参考日期。日期参数只接收有效 `YYYY-MM-DD` 或允许的 null，不解析“明天”等自然语言。

周/月视图需要较大的视图尺寸；缩小后切回列表和按天导航，保留当前日期与分区，重新放大后可再次选择周/月。

QML 只通过保存的请求上下文调用组件公开能力。桥接对象 `scheduleModel` 暴露 `dataJson`、`timeJson`、`lastError`、`refresh()`、`refreshTime()` 和 `invoke(operation, payloadJson)`；它不向 QML 提供可变存储对象。时间刷新错误与读写错误独立显示，成功刷新时间不会抹掉保存失败提示。

## 界面操作

宽视图直接切换“我的一天、收集箱、待重新安排、全部、已完成”，并显示数量。任务列表、周计划和月计划可直接切换；小视图用左上菜单选择列表。

- 输入任务后按回车保存，焦点留在输入栏便于连续添加。我的一天及周/月计划添加到选中日期，其余列表添加到收集箱。
- 点击任务打开详情；圆圈切换完成状态，星号切换重点，`⋯` 或右键可安排到今天/明天、移回收集箱、选择日期、上移/下移或删除。排序在同一日期范围内进行。
- 周/月计划左侧列出收集箱和待重新安排任务，拖动任务右侧的把手到日期列即可安排；每个日期的 `+` 将输入栏切换到该日期。改期保留已设定的钟点，移回收集箱会清空钟点。
- 日程视图内支持 `Ctrl+N` 聚焦添加、`Ctrl+F` 搜索、`Ctrl+Z` 撤销最近删除。删除后也可点击“撤销”。

交互参考 [Super Productivity](https://github.com/super-productivity/super-productivity) 的快速收集、每日任务和拖放计划流程，使用本组件自己的 QML 实现。

## 验证

```sh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=plugins/schedule python -m unittest discover -s tests -v
```
