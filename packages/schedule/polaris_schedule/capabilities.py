"""Discoverable business operation contracts for the schedule component."""
from copy import deepcopy

ID = {'type': 'string', 'minLength': 1, 'description': '已有任务返回的 id'}
DATE = {'type': ['string', 'null'], 'format': 'date', 'description': '有效 YYYY-MM-DD；null 表示收集箱'}
DAY = {'type': 'string', 'format': 'date', 'description': '有效 YYYY-MM-DD，不得为 null'}
TIME = {'type': 'string', 'pattern': r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$|^$',
        'description': 'HH:MM 或空字符串；收集箱只能为空。这是安排时间，不定义截止或提醒。'}
TITLE = {'type': 'string', 'minLength': 1, 'description': '去掉首尾空白后不能为空'}
FIELDS = {'title': TITLE, 'date': DATE, 'time': TIME, 'done': {'type': 'boolean'},
          'important': {'type': 'boolean'}, 'notes': {'type': 'string'}}
CHILD = {key: FIELDS[key] for key in ('title', 'done', 'notes')}


def operation(title, description, properties=None, required=()):
    return {'title': title, 'description': description,
            'parameters': {'type': 'object', 'properties': deepcopy(properties or {}),
                           'required': list(required), 'additionalProperties': False}}


BUSINESS_METADATA = {
    'get': operation('读取日程', '返回 {tasks, canUndo, storageNotice, timeContext}。任务字段为 id/title/date/time/done/important/notes/subtasks；子任务为 id/title/done/notes。timeContext 含 now/date/timezone。'),
    'time_context': operation('读取当前时间', '返回 {now, date, timezone:{name, utcOffsetMinutes}}；now 为带 UTC 偏移的 ISO 时间，date 为同一瞬间的本地日期。name 是系统时区名称或缩写，不保证为 IANA 标识。每次读取系统本地时间。'),
    'tasks': operation('查询任务', '返回任务数组。省略 date 查询全部；date=null 仅收集箱。query 搜索标题、笔记和子任务，默认空；include_done 默认 true。例如 {"date":"2026-11-04","include_done":false}。',
                       {'date': DATE, 'query': {'type': 'string', 'default': ''}, 'include_done': {'type': 'boolean', 'default': True}}),
    'add': operation('添加任务', '返回新任务。date 默认 null、time/notes 默认空、important 默认 false。例如 {"title":"会议","date":"2026-11-04","time":"09:00"}。',
                     {key: FIELDS[key] for key in ('title', 'date', 'time', 'notes', 'important')}, ('title',)),
    'update': operation('修改任务', '返回修改后的任务；只修改传入字段。identity 使用任务 id。date=null 放回收集箱；未同时传 time 时会清空旧时间。例如 {"identity":"任务id","done":true}。',
                        {'identity': ID, **FIELDS}, ('identity',)),
    'delete': operation('删除任务', '删除主任务并返回被删除的任务；可撤销最近一次删除。', {'identity': ID}, ('identity',)),
    'undo_delete': operation('撤销删除', '恢复最近删除的主任务或子任务并返回该对象；没有可撤销项返回 null。仅保留本次运行最近一次删除。'),
    'add_subtask': operation('添加子任务', '返回新子任务。identity 使用父任务 id。', {'identity': ID, 'title': TITLE}, ('identity', 'title')),
    'update_subtask': operation('修改子任务', '返回修改后的子任务；只修改传入字段。parent_id 是父任务 id，subtask_id 是子任务 id。',
                                {'parent_id': ID, 'subtask_id': {'type': 'string', 'minLength': 1, 'description': '子任务返回的 id'}, **CHILD}, ('parent_id', 'subtask_id')),
    'delete_subtask': operation('删除子任务', '删除并返回子任务，可撤销最近一次删除。parent_id 是父任务 id，subtask_id 是子任务 id。',
                                {'parent_id': ID, 'subtask_id': {'type': 'string', 'minLength': 1}}, ('parent_id', 'subtask_id')),
    'reorder': operation('排序任务', '返回范围内排序后的任务数组。省略 date 为全部，null 为收集箱。ids 必须完整包含范围内所有任务 id 且无重复。跨日期的查询仍按日期分组。',
                         {'ids': {'type': 'array', 'items': ID, 'uniqueItems': True}, 'date': DATE}, ('ids',)),
    'move_overdue': operation('批量改期', '将 today 之前未完成的有日期任务移动至 target_date，保留时间，返回变更任务数组。today 省略或 null 时使用日程时钟的当天日期；仅按日期判断，不判断当天已过时刻。',
                              {'target_date': DAY, 'today': {'type': ['string', 'null'], 'format': 'date', 'description': '参考日期 YYYY-MM-DD；省略或 null 使用日程时钟当天日期'}}, ('target_date',)),
    'organize_day': operation('整理某日', '原子地修改指定日期未完成任务，返回变更任务数组。changes 的 id 不得重复；可改日期、时间等字段，date=null 放回收集箱。',
                              {'date': DAY, 'changes': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': ID, **deepcopy(FIELDS)}, 'required': ['id'], 'additionalProperties': False}}}, ('date', 'changes')),
}
