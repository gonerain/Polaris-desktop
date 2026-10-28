# 日程组件 API

通过 `polaris_help({component:"calendar"})` 获取当前运行版本的操作说明，再用
`polaris_call({component:"calendar", operation, args})` 调用。Pi、Codex 共用这些操作，
插件只转发请求，不需要随着业务操作增加而升级。日程功能由运行中的 Polaris 提供，
更新源码后须重新运行应用；打包版本须重新构建后使用。

发现和 help 不读取日程内容。下表所有读取需要日程只读或修改授权，写入需要修改授权；
断线、应用重启或插件重载后授权失效。不会绕过授权或直接改 `tasks.json`。

## 操作范围

| 操作 | 权限 | 行为 |
| --- | --- | --- |
| `calendar.status` | read | 今天、全部/未完成/完成主任务数、收集箱与过期未完成数、保存状态、可撤销主任务 ID |
| `task.list` | read | 按日期、含首尾的日期范围、完成、重点、过期状态筛选，分页和关键词搜索 |
| `task.get` | read | 按 ID 读取摘要、子任务数量和已完成数量 |
| `task.create` | write | 创建标题、日期、时间、重点、完成状态；默认收集箱 |
| `task.update` | write | 编辑标题、日期、时间、重点和完成状态，至少一个字段 |
| `task.reschedule` | write | 改期，或移回收集箱并清除时间 |
| `task.complete` | write | 完成或取消完成主任务，不连带改变子任务 |
| `task.delete` | write | 删除主任务及所有子任务和笔记，提供单步撤销 |
| `task.restore` | write | 按删除的 ID 撤销最近一次主任务删除 |
| `task.reorder` | write | 将任务移到同日或同收集箱的另一个任务之前 |
| `task.move_overdue` | write | 显式将全部过期未完成任务移到今天，保留原时间 |
| `day.review` | write | 指定日期、逐项列出 ID，保留、移到次日或收集箱 |
| `subtask.list` / `subtask.get` | read | 指定主任务查询一级子任务；列表支持完成状态筛选和分页 |
| `subtask.create` / `subtask.update` | write | 创建、改标题、改完成状态 |
| `subtask.complete` | write | 完成或取消完成子任务，不改变主任务状态 |
| `subtask.delete` | write | 删除子任务及其笔记，不能撤销 |
| `subtask.reorder` | write | 在同一个主任务下移到另一个子任务之前 |
| `notes.get` | read | 显式分段读取主任务或子任务笔记，返回版本摘要 |
| `notes.set` / `notes.patch` | write | 全文替换、清空或分段修改笔记，可检查版本冲突 |

日期为严格 `YYYY-MM-DD`。`task.list` 省略 `date` 查询全部，`date:null` 仅收集箱，
`dateFrom/dateTo` 只查有日期的任务，不能与 `date` 混用；缺一端表示开放范围。
`overdue:true` 指今天以前且未完成，不包括今天早些时候的定时任务。
`calendar.status.inbox` 只计未完成的收集箱主任务。今天以 Polaris 本机日期为准。
查询不会改变正在浏览的日期，也不会自动顺延、完成子任务或替用户整理日程。

列表默认20条，最多100条，返回 `total` 和 `nextOffset`；按收集箱在前、日期升序、
同一天内的手动顺序返回。`task.reorder` 的 `beforeId` 表示插入到目标之前。
分页是当前状态的偏移分页，期间有新增、删除或排序时应重新查询，不是快照游标。
`query` 不区分大小写，默认匹配主任务和子任务标题；只有显式 `searchNotes:true`
才搜索笔记，且必须提供非空关键词。普通摘要不含笔记正文，但提供 `hasNotes`。
摘要标题最多2000字符，超长的旧标题带 `titleTruncated:true`，不能当作完整标题覆写。

## 删除指定任务与子任务

先按日期和标题定位，确认匹配结果，再按 ID 修改；不要把标题当成 ID。
以下 ID 仅为示例，须替换为实际查询返回值：

```json
{"component":"calendar","operation":"task.list","args":{"date":"2026-10-29","query":"11"}}
{"component":"calendar","operation":"task.delete","args":{"id":11}}
{"component":"calendar","operation":"task.list","args":{"date":"2026-10-29","query":"22"}}
{"component":"calendar","operation":"subtask.list","args":{"taskId":12}}
{"component":"calendar","operation":"subtask.delete","args":{"taskId":12,"id":13}}
```

子任务查询、编辑、排序、删除必须指定所属主任务 `taskId`；不匹配则 `not_found`，
防止误操作其他主任务下的同名子任务。子任务只有一级，不独立设置日期、时间或重点。
主任务和子任务的完成状态各自独立。

主任务删除返回 `deleted` 摘要和 `undoTaskId`。`task.restore({id})` 只恢复当前最近删除的
主任务，保留其 ID、日期、顺序、子任务、重点、时间和笔记。后续主任务删除会覆盖撤销记录，
重启后不保留。`calendar.status` 可查询当前 `undoTaskId`；不匹配返回 `conflict`，
不会误撤销另一条任务。子任务删除沿用现有不可撤销行为。

## 笔记与并发编辑

`notes.get/set/patch` 均以 `taskId` 定位主任务；可选 `subtaskId` 定位其子任务笔记。
`notes.get` 默认2000、最多4000个 Unicode 字符，返回 `offset,total,text,nextOffset,revision`。
换行、中文、emoji 均按 Python Unicode 字符计数，不按 UTF-8 字节或 JavaScript UTF-16 单元计数。
读取多段期间若 `revision` 改变，应重新读取，不把不同版本拼在一起。

`notes.set` 的 `text` 最多8000字符，空字符串清空；建议携带读取返回的 `expectedRevision`。
`notes.patch` 必须带当前 `expectedRevision`，将 `offset` 起的 `deleteCount` 个字符替换为
`text`（每次最多8000字符），可分段编辑超过8000字符的旧笔记。
偏移或删除范围越界返回 `invalid_params`。版本不匹配返回 `conflict`，不覆盖其他编辑。
写入仅返回新 `revision`、`length` 和保存状态，不回传笔记全文。

## 写入与失败语义

全部修改经过同一个 `CalendarTaskStore`，保留 Qt 信号和自动保存行为。
一条多字段更新、创建带状态的任务或日终整理会先校验所有参数，再合并为一次保存。
非法参数不会造成部分修改；这不是跨多个工具调用的事务。

`day.review` 最多100个决定，每项只有 `{id,action}`，action 为 `keep/tomorrow/inbox`。
重复 ID、已完成、已改期或不存在的任务会拒绝整次请求；未列出的任务保持原样。
9999-12-31 不能移到次日。移到收集箱会清时间，移到次日保留时间。

写入返回 `{applied,persisted,storageError,...}`。`applied:true` 代表内存已应用，不能因为
`persisted:false` 就重复写入。保存失败时保留内存修改，后续外部写入返回
`storage_unavailable`，读取仍可使用；由用户在界面重试保存，不额外暴露文件修复能力。
无磁盘存储的诊断实例返回 `persisted:false`。

写调用断线或超时、返回 `result_too_large` 时，先查询实际状态，不盲目重试。
列表遇到单帧65,536字节限制应缩小 `limit`；笔记采用分段读取。
参数名、类型、布尔值、ID、日期、时间和 Unicode 严格校验，未知字段拒绝。

## 验证

用内联诊断和临时日程验证全部22个操作、权限拒绝、参数无副作用、笔记版本冲突、
父子 ID 约束、单次保存、删除恢复、保存失败保护与重新加载。另通过临时本机桥及
现有 MCP 服务验证 help 与主/子任务删除链路，不访问真实用户日程。
