"""Schedule business rules, independent of presentation and platform services."""
from copy import deepcopy
from datetime import date as Date
import re
from uuid import uuid4
from functools import wraps
from threading import RLock

from .storage import SnapshotRepository, StorageError

ANY = object()


def valid_date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('日期必须为 YYYY-MM-DD 或 null')
    try:
        if Date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError('日期必须为有效的 YYYY-MM-DD') from None
    return value


def _entry(value, child=False):
    fields = {'id', 'title', 'done', 'notes'} if child else {'id', 'title', 'date', 'time', 'done', 'important', 'notes', 'subtasks'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('任务字段无效')
    if not isinstance(value['id'], str) or not value['id']:
        raise ValueError('任务编号无效')
    if not isinstance(value['title'], str) or not value['title'].strip():
        raise ValueError('任务标题不能为空')
    if type(value['done']) is not bool or not isinstance(value['notes'], str):
        raise ValueError('任务完成状态或笔记无效')
    if child:
        return
    valid_date(value['date'])
    if not isinstance(value['time'], str) or (value['time'] and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value['time']) is None):
        raise ValueError('时间必须为 HH:mm 或空字符串')
    if value['date'] is None and value['time']:
        raise ValueError('收集箱任务不能设置时间')
    if type(value['important']) is not bool or not isinstance(value['subtasks'], list):
        raise ValueError('重点状态或子任务无效')
    for subtask in value['subtasks']:
        _entry(subtask, True)


def validate_snapshot(value):
    if not isinstance(value, dict) or set(value) != {'version', 'tasks'} or type(value['version']) is not int or value['version'] != 1 or not isinstance(value['tasks'], list):
        raise ValueError('日程文件版本或格式无效')
    ids = set()
    for task in value['tasks']:
        _entry(task)
        for item in [task, *task['subtasks']]:
            if item['id'] in ids:
                raise ValueError('任务编号重复')
            ids.add(item['id'])


def _locked(method):
    @wraps(method)
    def synchronized(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return synchronized


class ScheduleStore:
    def __init__(self, path=None):
        self._lock = RLock()
        self._repository = SnapshotRepository(path, validate_snapshot) if path is not None else None
        self._data = self._repository.load() if self._repository else {'version': 1, 'tasks': []}
        self._undo = None

    @property
    @_locked
    def storage_notice(self):
        return self._repository.notice if self._repository else ''

    @property
    @_locked
    def can_undo(self):
        return self._undo is not None

    def _commit(self, data, undo=ANY):
        validate_snapshot(data)
        if self._repository:
            self._repository.save(data)
        self._data = data
        if undo is not ANY:
            self._undo = undo

    def _find(self, identity, data=None):
        for task in (data if data is not None else self._data)['tasks']:
            if task['id'] == identity:
                return task
        raise KeyError(identity)

    @_locked
    def get(self, identity):
        return deepcopy(self._find(identity))

    @_locked
    def tasks(self, date=ANY, query='', include_done=True):
        if date is not ANY:
            valid_date(date)
        if not isinstance(query, str) or type(include_done) is not bool:
            raise ValueError('搜索条件无效')
        query = query.casefold().strip()
        values = [task for task in self._data['tasks'] if (date is ANY or task['date'] == date) and (include_done or not task['done']) and (not query or query in ' '.join([task['title'], task['notes'], *[part for sub in task['subtasks'] for part in (sub['title'], sub['notes'])]]).casefold())]
        return deepcopy(sorted(values, key=lambda task: (task['date'] is None, task['date'] or '')))

    @_locked
    def add(self, title, date=None, time='', notes='', important=False):
        task = {'id': uuid4().hex, 'title': title.strip() if isinstance(title, str) else title, 'date': date, 'time': time, 'notes': notes, 'important': important, 'done': False, 'subtasks': []}
        data = deepcopy(self._data)
        data['tasks'].append(task)
        self._commit(data)
        return deepcopy(task)

    @staticmethod
    def _update(task, fields, child=False):
        allowed = {'title', 'done', 'notes'} if child else {'title', 'date', 'time', 'done', 'important', 'notes'}
        if not fields.keys() <= allowed:
            raise ValueError('不支持的任务字段')
        task.update(fields)
        if 'title' in fields and isinstance(task['title'], str):
            task['title'] = task['title'].strip()
        if not child and task['date'] is None and 'time' not in fields:
            task['time'] = ''
        _entry(task, child)

    @_locked
    def update(self, identity, **fields):
        data = deepcopy(self._data)
        task = self._find(identity, data)
        self._update(task, fields)
        self._commit(data)
        return deepcopy(task)

    @_locked
    def delete(self, identity):
        data = deepcopy(self._data)
        task = self._find(identity, data)
        index = data['tasks'].index(task)
        data['tasks'].pop(index)
        self._commit(data, ('task', index, deepcopy(task)))
        return deepcopy(task)

    @_locked
    def undo_delete(self):
        if self._undo is None:
            return None
        data = deepcopy(self._data)
        kind, location, task = self._undo
        if kind == 'task':
            data['tasks'].insert(location, deepcopy(task))
        else:
            parent, index = location
            self._find(parent, data)['subtasks'].insert(index, deepcopy(task))
        self._commit(data, None)
        return deepcopy(task)

    @_locked
    def add_subtask(self, identity, title):
        data = deepcopy(self._data)
        task = self._find(identity, data)
        sub = {'id': uuid4().hex, 'title': title.strip() if isinstance(title, str) else title, 'done': False, 'notes': ''}
        task['subtasks'].append(sub)
        self._commit(data)
        return deepcopy(sub)

    @_locked
    def update_subtask(self, parent_id, subtask_id, **fields):
        data = deepcopy(self._data)
        sub = next((sub for sub in self._find(parent_id, data)['subtasks'] if sub['id'] == subtask_id), None)
        if sub is None:
            raise KeyError(subtask_id)
        self._update(sub, fields, True)
        self._commit(data)
        return deepcopy(sub)

    @_locked
    def delete_subtask(self, parent_id, subtask_id):
        data = deepcopy(self._data)
        children = self._find(parent_id, data)['subtasks']
        index = next((i for i, sub in enumerate(children) if sub['id'] == subtask_id), None)
        if index is None:
            raise KeyError(subtask_id)
        sub = children.pop(index)
        self._commit(data, ('subtask', (parent_id, index), deepcopy(sub)))
        return deepcopy(sub)

    @_locked
    def reorder(self, ids, date=ANY):
        if date is not ANY:
            valid_date(date)
        selected = [task for task in self._data['tasks'] if date is ANY or task['date'] == date]
        if not isinstance(ids, list) or len(ids) != len(selected) or any(not isinstance(identity, str) or not identity for identity in ids) or set(ids) != {task['id'] for task in selected}:
            raise ValueError('排序必须包含范围内每个任务且不得重复')
        data = deepcopy(self._data)
        mapping = {task['id']: task for task in data['tasks']}
        ordered = iter(mapping[identity] for identity in ids)
        data['tasks'] = [next(ordered) if date is ANY or task['date'] == date else task for task in data['tasks']]
        self._commit(data)
        return self.tasks(date=date)

    @_locked
    def move_overdue(self, target_date, today=None):
        valid_date(target_date)
        if target_date is None:
            raise ValueError('目标日期不能为空')
        today = Date.today().isoformat() if today is None else valid_date(today)
        if today is None:
            raise ValueError('今日日期不能为空')
        changes = [{'id': task['id'], 'date': target_date} for task in self._data['tasks'] if task['date'] is not None and task['date'] < today and not task['done']]
        return self._batch(changes)

    def _batch(self, changes, source=ANY):
        if not isinstance(changes, list):
            raise ValueError('整理变更必须是列表')
        data = deepcopy(self._data)
        result, seen = [], set()
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get('id'), str) or not change['id'] or change['id'] in seen:
                raise ValueError('整理任务编号无效或重复')
            seen.add(change['id'])
            task = self._find(change['id'], data)
            if source is not ANY and (task['date'] != source or task['done']):
                raise ValueError('日整理仅支持当天未完成任务')
            self._update(task, {key: value for key, value in change.items() if key != 'id'})
            result.append(deepcopy(task))
        self._commit(data)
        return result

    @_locked
    def organize_day(self, date, changes):
        valid_date(date)
        if date is None:
            raise ValueError('整理日期不能为空')
        return self._batch(changes, source=date)
