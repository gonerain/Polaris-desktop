# 日程组件

独立的本地任务组件，组件 ID 为 `org.polaris.schedule`。业务在无界面时即可使用；`main` 视图通过公开的 `qt-quick-item` 契约呈现。

## 启动与装配

在仓库根目录运行：

```sh
PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.schedule.json
```

此配置装配基础组件和自动启动的日程组件。已有应用可通过桌宠右键菜单的“组件管理”打开管理窗口，选择“加载组件”，选择本目录，然后启动“日程”。在画布的添加入口选择“日程 · 日程”，按提示授权视图所列的读取和写入能力。操作权限由调用来源持有，已经显示的视图也会受后续撤权限制。

`create_view(view="main", parent=QQuickItem)` 返回 `{handle, item}`；`release_view(handle)` 只释放视图。隐藏、移除视图不停止日程业务，重新打开可读取已保存内容。停止组件会释放其全部视图。

## 本地数据

默认保存在 Windows 的 `%LOCALAPPDATA%/polaris-schedule`，或 Linux 的 `$XDG_DATA_HOME/polaris-schedule`（未设置时为 `~/.local/share/polaris-schedule`）。`schedule.json` 保存任务，并保留备份和损坏恢复信息。工厂参数 `data_dir` 可显式覆盖目录，例如在 manifest 的 `entry.kwargs` 中设置绝对路径。保存失败会明确显示错误，界面保留尚未提交的输入。

## 能力接口

所有能力均为 revision 1；读取为 `read`，变更为 `write`。无需获取视图即可调用：

- `get()` 返回 `{tasks, canUndo, storageNotice}`；任务包含 `id/title/date/time/done/important/notes/subtasks`。
- `tasks(date?, query="", include_done=true)` 查询任务。`date=null` 仅查询收集箱；省略日期查询全部任务。
- `add(title, date=null, time="", notes="", important=false)` 新增任务，返回任务对象。
- `update(identity, ...fields)` 修改任务字段；`date=null` 放回收集箱。
- `delete(identity)` 删除主任务；`undo_delete()` 恢复最近删除的主任务。
- `add_subtask(identity, title)`；`update_subtask(parent_id, subtask_id, ...fields)`；`delete_subtask(parent_id, subtask_id)` 管理子任务。子任务字段为 `title/done/notes`。
- `reorder(ids, date?)` 调整任务顺序。
- `move_overdue(target_date, today?)` 将过期未完成任务移到目标日期。
- `organize_day(date, changes)` 按 `[{id, ...fields}]` 批量整理指定日期的任务；由用户选择保留、改期或放回收集箱。

主任务支持收集箱、日期与时间、重点、完成、笔记、子任务、改期和删除撤销。界面提供我的一天、任务库、周/月计划、完成记录和搜索。日期格式为 `YYYY-MM-DD`，时间为 `HH:MM` 或空字符串。

QML 只通过保存的请求上下文调用组件公开能力。桥接对象 `scheduleModel` 暴露 `dataJson`、`lastError`、`refresh()` 和 `invoke(operation, payloadJson)`；它不向 QML 提供可变存储对象。

## 验证

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=next .venv/bin/python -m unittest discover -s next/tests -p 'test_schedule*.py'
```
