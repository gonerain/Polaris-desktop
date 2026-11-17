"""Run-local result references keep model context bounded without losing data."""
from copy import deepcopy
import json


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def preview(value, depth=0):
    if depth > 2:
        return {'type': type(value).__name__, 'items': len(value)} if isinstance(value, (dict, list)) else str(value)[:160]
    if isinstance(value, dict):
        result = {k: preview(v, depth + 1) for k, v in list(value.items())[:16]}
        if len(value) > 16:
            result['_remaining_keys'] = len(value) - 16
        return result
    if isinstance(value, list):
        return {'count': len(value), 'first': [preview(v, depth + 1) for v in value[:2]]}
    if isinstance(value, str) and len(value) > 240:
        return value[:240] + '…'
    return value


class Results:
    def __init__(self):
        self.values = {}
        self.references = {}

    def add(self, call_id, value):
        ref = 'r' + str(len(self.values) + 1)
        self.values[ref] = deepcopy(value)
        self.references[call_id] = ref
        raw = encode(value)
        return raw if len(raw) <= 6000 else self.summary(ref)

    def summary(self, ref):
        value = self.values[ref]
        small = preview(value)
        if len(encode(small)) > 2000:
            small = {'type': type(value).__name__, 'keys': list(value)[:24] if isinstance(value, dict) else None}
        return encode(dict(result_ref=ref, total_chars=len(encode(value)), preview=small,
                           notice='这是部分预览。用 read_result 按 JSON Pointer 路径读取需要的字段；原始结果仍完整保留。'))

    def read(self, result_ref, path='', offset=0, limit=3000):
        if result_ref not in self.values:
            raise ValueError('结果引用不属于本轮')
        if not isinstance(path, str) or path and not path.startswith('/'):
            raise ValueError('path 必须为 JSON Pointer，例如 /sessions/0/id')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4000:
            raise ValueError('无效的读取范围')
        value = self.values[result_ref]
        for part in path.split('/')[1:] if path else []:
            key = part.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
        raw = encode(value)
        if offset == 0 and len(raw) <= limit:
            return dict(value=deepcopy(value), more=False)
        return dict(text=raw[offset:offset+limit], offset=offset, total_chars=len(raw), more=offset + limit < len(raw))

    def select(self, result_ref, path='', where=None, fields=None, offset=0, limit=50):
        if result_ref not in self.values:
            raise ValueError('结果引用不属于本轮')
        if not isinstance(path, str) or path and not path.startswith('/'):
            raise ValueError('path 必须为 JSON Pointer')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('无效的分页范围')
        where = {} if where is None else where
        if not isinstance(where, dict) or len(where) > 20 or any(not isinstance(k, str) or
                type(v) not in (str, int, float, bool, type(None)) for k, v in where.items()):
            raise ValueError('where 仅支持顶层字段与 JSON 标量精确匹配')
        if fields is not None and (not isinstance(fields, list) or not 1 <= len(fields) <= 20 or
                                  any(not isinstance(k, str) or not k for k in fields)):
            raise ValueError('fields 必须包含 1–20 个顶层字段名')
        value = self.values[result_ref]
        for part in path.split('/')[1:] if path else []:
            key = part.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
        if not isinstance(value, list):
            raise ValueError('选择目标必须为数组')
        matched = [row for row in value if isinstance(row, dict) and all(
            k in row and row[k] == v and (isinstance(row[k], bool) == isinstance(v, bool))
            for k, v in where.items())]
        page = matched[offset:offset + limit]
        items = [{k: deepcopy(row[k]) for k in fields if k in row} for row in page] if fields else deepcopy(page)
        return dict(items=items, matched=len(matched), offset=offset, more=offset + len(page) < len(matched))

    def fit(self, messages, max_bytes=48000):
        result = deepcopy(messages)
        if len(encode(result).encode()) <= max_bytes:
            return result
        for message in result:
            ref = self.references.get(message.get('tool_call_id'))
            if message.get('role') == 'tool' and ref:
                message['content'] = encode(dict(result_ref=ref, notice='较早结果已收起，需要时用 read_result 读取。'))
                if len(encode(result).encode()) <= max_bytes:
                    return result
        raise ValueError('本轮上下文超过预算，请缩小请求范围')
