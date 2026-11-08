"""One model/tool loop with explicit limits, cancellation, and run-local results."""
from dataclasses import dataclass
import json
import time
from .context import Results
from .model import MODEL_TIMEOUT, ModelError
from .instructions import SYSTEM
from polaris_platform.protocol import PlatformError

RUN_TIMEOUT = 300


def _tool(name, description, properties, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties, 'required': list(required),
                       'additionalProperties': False}}}


TOOLS = [
    _tool('components', '查看可用组件及操作名称摘要', {}),
    _tool('help', '读取目标操作的参数说明',
          {'component': {'type': 'string'}, 'operation': {'type': 'string'}}, ['component']),
    _tool('call', '调用已授权的组件操作；先用 help 确认参数', {
        'component': {'type': 'string'}, 'operation': {'type': 'string'},
        'arguments': {'type': 'object'}}, ['component', 'operation', 'arguments']),
    _tool('read_result', '按需读取本轮工具原始结果，不会再次执行业务操作', {
        'result_ref': {'type': 'string'}, 'path': {'type': 'string'},
        'offset': {'type': 'integer', 'minimum': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 4000}}, ['result_ref']),
    _tool('select_result', '从本轮结果数组批量筛选与提取字段，不重新调用业务操作。where 按顶层字段精确匹配，fields 为顶层字段名。', {
        'result_ref': {'type': 'string'}, 'path': {'type': 'string'},
        'where': {'type': 'object'}, 'fields': {'type': 'array', 'items': {'type': 'string'}},
        'offset': {'type': 'integer', 'minimum': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['result_ref']),
]


@dataclass
class AgentResult:
    text: str
    history: list


class AgentLoop:
    def __init__(self, model, max_calls=8, max_tools=12):
        self.model, self.max_calls, self.max_tools = model, max_calls, max_tools

    def _safe(self, value):
        return getattr(self.model, 'redact', str)(str(value))

    def run(self, text, history, tools_executor, cancel):
        if hasattr(self.model, 'begin_run'):
            self.model.begin_run()
        deadline, calls = time.monotonic() + RUN_TIMEOUT, 0
        results, used_ids = Results(), set()
        messages = [{'role': 'system', 'content': SYSTEM}]
        if getattr(tools_executor, 'allowed', False) and hasattr(tools_executor, 'catalog'):
            catalog = tools_executor.catalog()
            messages[0]['content'] += '\n本轮授权工具目录（提供完整 parameters 的操作可直接 call，其余先 help）：\n' + json.dumps(catalog, ensure_ascii=False)
        for entry in (history or [])[-12:]:
            if isinstance(entry, dict) and entry.get('role') in ('user', 'assistant'):
                messages.append({'role': entry['role'], 'content': self._safe(entry.get('content', ''))[:3000]})
        while len(json.dumps(messages, ensure_ascii=False).encode()) > 20000 and len(messages) > 2:
            del messages[1:3]
        messages.append({'role': 'user', 'content': self._safe(text)[:8000]})

        def active():
            if cancel.is_set():
                raise ModelError('请求已取消')
            if time.monotonic() >= deadline:
                raise ModelError('请求超时')

        for step in range(self.max_calls):
            active()
            final = step == self.max_calls - 1 or calls >= self.max_tools
            if final:
                messages.append({'role': 'system', 'content': '本轮预算已用完。根据已有结果简短回复成功、失败或待确认状态，不再调用工具。'})
            toolset = [] if final or not getattr(tools_executor, 'allowed', True) else TOOLS
            try:
                context = results.fit(messages)
            except ValueError as error:
                raise ModelError(str(error)) from None
            response = self.model.complete(context, toolset, cancel, timeout=min(MODEL_TIMEOUT, max(.1, deadline-time.monotonic())))
            active()
            if not isinstance(response, dict):
                raise ModelError('模型响应格式无效')
            tool_calls = response.get('tool_calls')
            if tool_calls is None:
                tool_calls = []
            if not isinstance(tool_calls, list):
                raise ModelError('模型工具响应格式无效')
            if not tool_calls:
                answer = response.get('content')
                if not isinstance(answer, str) or not answer.strip():
                    raise ModelError('模型未返回有效正文')
                answer = self._safe(answer)
                return AgentResult(answer, [{'role': 'user', 'content': self._safe(text)[:8000]},
                                            {'role': 'assistant', 'content': answer}])
            if final or len(tool_calls) > self.max_tools - calls:
                raise ModelError('工具调用次数超过预算')
            if any(not isinstance(call, dict) or not isinstance(call.get('id'), str) or not call['id'] for call in tool_calls):
                raise ModelError('模型工具调用缺少有效标识')
            ids = {call['id'] for call in tool_calls}
            if len(ids) != len(tool_calls) or ids & used_ids:
                raise ModelError('模型工具调用标识重复')
            used_ids.update(ids)
            messages.append(response)
            for call in tool_calls:
                active()
                calls += 1
                try:
                    function = call['function']
                    name, args = function['name'], json.loads(function.get('arguments', '{}'))
                    if not isinstance(args, dict):
                        raise ValueError('工具参数必须是对象')
                    if name == 'read_result':
                        value = results.read(**args)
                    elif name == 'select_result':
                        value = results.select(**args)
                    elif name in ('components', 'help', 'call'):
                        value = tools_executor.execute(name, args, cancel)
                    else:
                        raise ValueError('未知工具')
                    value = json.loads(self._safe(json.dumps(value, ensure_ascii=False, default=str)))
                except (InterruptedError, ModelError):
                    raise
                except Exception as error:
                    value = {'error': self._safe(error)}
                    if isinstance(error, PlatformError):
                        value['code'] = error.code
                        if error.code == 'permission_required':
                            details = error.details if isinstance(error.details, dict) else {}
                            cap = details.get('capability', [])
                            value.update(requester=details.get('requester'),
                                         operation=cap[2] if isinstance(cap, (list, tuple)) and len(cap) > 2 else args.get('operation'),
                                         component=args.get('component'))
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': results.add(call['id'], value)})
        raise ModelError('本轮模型请求次数已用完')
