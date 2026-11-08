from copy import deepcopy
import json
from polaris_platform.protocol import PlatformError


def operations(record):
    return {name: meta for name, meta in record.get('description', {}).get('operations', {}).items()
            if isinstance(meta, dict) and meta.get('available', True) and meta.get('profile') != 'qt-native' and not meta.get('humanOnly') and meta.get('modelCallable') is not False}


class ToolExecutor:
    def __init__(self, ctx, allowed, directory_id, own_id=None, completions=None, caller=None):
        self.ctx, self.directory_id, self.own_id = ctx, directory_id, own_id
        self.excluded = {self.directory_id, self.own_id, caller}
        self.allowed = {(r['target'], r['operation']) for r in allowed}
        self.explained = {}
        self.writes = {}
        self._records = None
        self.completions = completions

    def resolve_component(self, value):
        if not isinstance(value, str) or not value.strip():
            raise PlatformError('invalid_params', '缺少组件名称')
        value = value.strip()
        if value in self.excluded:
            raise PlatformError('denied', '该组件未在本次调用的允许列表中启用')
        allowed_targets = {target for target, _ in self.allowed}
        if value in allowed_targets:
            return value
        if self._records is None:
            self._records = self.ctx.call(self.directory_id, 'discover', {}).get('components', [])
        exact = next((row for row in self._records if row.get('id') == value), None)
        matches = [exact] if exact else [row for row in self._records if value.casefold() in
            (str(row.get('id', '')).casefold(), str(row.get('manifest', {}).get('name', '')).casefold(),
             str(row.get('id', '')).rsplit('.', 1)[-1].casefold())]
        if len(matches) > 1:
            raise PlatformError('ambiguous_component', '组件名称不唯一，请使用组件列表中的完整 id')
        if not matches:
            raise PlatformError('component_not_found', '组件名称不存在，请从组件列表中选择完整 id；这不是权限错误')
        identity = matches[0]['id']
        if identity not in allowed_targets or identity in self.excluded:
            raise PlatformError('denied', '该组件未在本次调用的允许列表中启用')
        return identity

    def execute(self, name, args, cancel):
        if cancel.is_set():
            raise InterruptedError()
        if name == 'components':
            records = self.ctx.call(self.directory_id, 'discover', {}).get('components', [])
            self._records = records
            filtered = [self.filtered(r) for r in records if any(t == r.get('id') for t, _ in self.allowed)]
            return {'components': [dict(id=r['id'], name=r['name'], operations=[
                dict(name=n, title=m.get('title', n), access=m.get('access', 'read'))
                for n, m in r['description']['operations'].items()])
                for r in filtered if r['description']['operations']]}
        target = self.resolve_component(args.get('component'))
        if name == 'help':
            record = self.filtered(self.ctx.call(self.directory_id, 'describe', {'target': target}))
            operation = args.get('operation')
            if operation is not None:
                entries = record['description']['operations']
                if operation not in entries:
                    raise PlatformError('denied', '本次委托未启用此操作')
                record['description']['operations'] = {operation: entries[operation]}
            self.explained.update({(target, op): deepcopy(meta) for op, meta in record['description']['operations'].items()})
            return record
        if name != 'call':
            raise PlatformError('invalid_params', '未知工具')
        operation = args.get('operation')
        if (target, operation) not in self.allowed:
            raise PlatformError('denied', '该操作未在本次调用的允许列表中启用')
        if (target, operation) not in self.explained:
            raise PlatformError('help_required', '请先查询此组件的操作说明；这不是权限错误')
        arguments = args.get('arguments', {})
        if not isinstance(arguments, dict):
            raise PlatformError('invalid_params', '操作参数必须是对象')
        live = self.filtered(self.ctx.call(self.directory_id, 'describe', {'target': target}))
        metadata = live['description']['operations'].get(operation)
        if metadata != self.explained.get((target, operation)):
            raise PlatformError('stale_handle', '操作说明已改变，请重新查询帮助')
        if cancel.is_set():
            raise InterruptedError()
        if metadata.get('access') != 'write':
            return self.ctx.call(target, operation, arguments)
        key = (target, operation, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if key in self.writes:
            result, error = self.writes[key]
            if error:
                raise PlatformError('unknown_result', '该写操作已尝试，本轮不会重复提交')
            return deepcopy(result)
        self.writes[key] = (None, True)
        if self.completions is not None:
            arguments = self.completions.prepare(target, metadata, arguments)
        result = self.ctx.call(target, operation, arguments)
        self.writes[key] = (deepcopy(result), False)
        return result

    def catalog(self):
        """Provide bounded, authorized schemas before the first model request."""
        records = self.ctx.call(self.directory_id, 'discover', {}).get('components', [])
        self._records = records
        entries, size = [], 0
        for record in records:
            target = record.get('id')
            if target in self.excluded:
                continue
            for name, metadata in self.filtered(record)['description']['operations'].items():
                base = dict(component=target, operation=name, title=metadata.get('title', name),
                            access=metadata.get('access', 'read'))
                full = dict(base, description=metadata.get('description', ''), parameters=metadata.get('parameters'))
                length = len(json.dumps(full, ensure_ascii=False).encode())
                if metadata.get('parameters') is not None and length <= 4000 and size + length <= 10000:
                    entries.append(full)
                    self.explained[(target, name)] = deepcopy(metadata)
                    size += length
                else:
                    length = len(json.dumps(base, ensure_ascii=False).encode())
                    if size + length > 12000:
                        return dict(operations=entries, more=True, notice='其余操作使用 components 和 help 查询')
                    entries.append(base)
                    size += length
        return dict(operations=entries, more=False)

    def filtered(self, record):
        return {'id': record.get('id'),
                'name': record.get('manifest', {}).get('name', record.get('id')),
                'description': {'operations': {n: deepcopy(m) for n, m in operations(record).items()
                                               if (record.get('id'), n) in self.allowed}}}

    def failure_reply(self, reason):
        lines = ['本次处理未能正常结束：' + reason]
        completed, unknown, pending, accepted, rejected = [], [], [], [], []
        for (target, operation, _), (result, failed) in self.writes.items():
            metadata = self.explained.get((target, operation), {})
            label = target + ' · ' + metadata.get('title', operation)
            status = result.get('status') if isinstance(result, dict) else None
            bucket = unknown if failed else {'pending': pending, 'unknown': unknown,
                                              'accepted': accepted, 'rejected': rejected}.get(status, completed)
            bucket.append(label)
        if completed:
            lines.append('已确认执行成功：' + '、'.join(dict.fromkeys(completed)) + '。无需重复操作。')
        if unknown:
            lines.append('结果未确认：' + '、'.join(dict.fromkeys(unknown)) + '。请先查询实际状态。')
        if pending:
            lines.append('已提交，等待接收方确认：' + '、'.join(dict.fromkeys(pending)) + '。请查询投递状态。')
        if accepted:
            lines.append('接收方已接收：' + '、'.join(dict.fromkeys(accepted)) + '。运行结果需另行查询。')
        if rejected:
            lines.append('接收方已拒绝：' + '、'.join(dict.fromkeys(rejected)) + '。')
        return '\n'.join(lines)[:1800]
