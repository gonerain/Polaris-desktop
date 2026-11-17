# 日程组件

支持本地任务与 Google Calendar 只读安排的日程组件，组件 ID 为 `org.polaris.schedule`。业务在无界面时即可使用；`main` 视图通过公开的 `qt-quick-item` 契约呈现。

## 启动与装配

安装兼容的 Polaris 平台 SDK 后，可从本仓库根目录使用公开模块入口启动：

```sh
python -m polaris_platform --gui --config config.schedule.json
```

也可在组件管理中添加本仓库为插件源，安装并启动“日程”，再从画布添加日程视图。视图申请 `get`、`time_context` 读取权限及实际使用的写入权限；已显示的视图仍受撤权限制。

`create_view(view="main", parent=QQuickItem)` 返回 `{handle, item}`；`release_view(handle)` 只释放视图。隐藏、移除视图不停止日程业务，重新打开可读取已保存内容。停止组件会释放其全部视图。

## 本地数据

默认保存在 Windows 的 `%LOCALAPPDATA%/polaris-schedule`，或 Linux 的 `$XDG_DATA_HOME/polaris-schedule`（未设置时为 `~/.local/share/polaris-schedule`）。`schedule.json` 保存任务，并保留备份和损坏恢复信息。工厂参数 `data_dir` 可显式覆盖目录，例如在 manifest 的 `entry.kwargs` 中设置绝对路径。保存失败会明确显示错误，界面保留尚未提交的输入。

## Google Calendar 只读同步

在日程顶部点击 **Google 日历** 打开连接设置：

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建项目并启用 **Google Calendar API**。
2. 配置 Google Auth Platform 的应用信息、受众和数据访问。测试模式下将自己的 Google 账号加入测试用户。
3. 创建类型为 **桌面应用** 的 OAuth 客户端，下载客户端 JSON（不是服务账号密钥，也不是 Web 客户端）。
4. 在日程设置中选择该 JSON，点击“连接 Google”，在系统浏览器中选择账号并授予日历读取权限。
5. 默认展示主日历；勾选需要显示的其他日历并点击“保存选择”。

事件显示在“我的一天”“全部”、搜索和周/月计划中。点击可查看时间、地点、说明以及打开 Google Calendar。支持全天、跨天和重复事件；全天结束日期按 Google 的排他结束语义处理，带时间事件按系统本地时间显示。当前仅查看，不编辑、创建或删除 Google 事件。

同步范围为过去 90 天至未来一年。连接后、组件启动时和运行期间每 5 分钟同步，也可手动刷新。首次分页读取，之后按日历保存 `syncToken` 增量读取；本地日期变化时刷新同步窗口，服务端返回 `410` 时重新读取相应日历。所有分页成功后才提交缓存和新 token。失败保留旧缓存，设置中显示错误及最近同步时间；不表示实时推送。

OAuth 使用系统浏览器、随机本地回调端口、state 和 PKCE；等待浏览器授权不设总时限，可主动取消。仅请求 `calendar.calendarlist.readonly` 与 `calendar.events.readonly`。客户端配置和刷新令牌存于 Linux Secret Service（需系统 `libsecret-1` 和已解锁的凭据库）或 Windows 凭据管理器，不写入任务文件或事件缓存；不支持明文凭据回退。测试模式下 Google 可能使刷新令牌在 7 天后失效，届时重新连接；公开发布需按所选权限完成 Google 的验证要求。

`google-calendar.json` 独立保存日历选择、事件、同步状态，不改变 `schedule.json`。断开会删除本机凭据与事件缓存；如需撤销 Google 端授权，请前往 Google 账号的第三方应用设置。JSON 客户端文件选择完成后无需保留在原路径，建议妥善保管原文件。

新增能力（均为 `write`，异步接受后通过 `get().google` 读取状态）：
- `google_connect(client_file)`：导入桌面客户端 JSON 并开始浏览器授权。
- `google_cancel()`：取消等待中的授权。
- `google_select(calendar_ids)`：保存并同步所选日历；空数组隐藏全部日历。
- `google_sync()`：手动刷新。
- `google_disconnect()`：断开本机连接。

`get().google` 含 `connected/calendars/selected/events/lastSync/busy/error/authorizing/authUrl`。事件包含 `id/calendarId/calendarTitle/color/title/start/end/location/description/url/recurring/googleEvent`；`start/end` 保留 Google API 的 `date` 或 `dateTime/timeZone`。网络工作不占用界面线程，移除视图不停止同步，停止组件会取消授权等待并停止后续同步。

参考：[桌面 OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)、[Calendar 增量同步](https://developers.google.com/workspace/calendar/api/guides/sync)。

## 能力接口

所有能力均为 revision 1；读取为 `read`，变更为 `write`。业务操作明确提供 `polaris.schedule.<操作的短横线名称>@1` 契约及 `applicationBinding='instance'`，供日程应用按稳定实例连接。无需获取视图即可调用：

- `get()` 返回 `{tasks, canUndo, storageNotice, timeContext, google}`；任务包含 `id/title/date/time/done/important/notes/subtasks`。
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
TZ=Asia/Shanghai QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=next:marketplace/packages/schedule python -m unittest discover -s marketplace/packages/schedule/tests -v
```
