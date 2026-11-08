"""Private SDK process. One process owns one bot, including SDK global state."""
import asyncio
from dataclasses import fields, is_dataclass
from enum import Enum
import re
import json
import logging
import queue
import os
import sys
import threading
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))


def json_value(value):
    if is_dataclass(value):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value) if field.name != 'raw'}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items() if key != 'raw'}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value if isinstance(value, (str, int, float, bool)) or value is None else None


def safe_error(error, operation=None):
    raw_code = getattr(error, 'raw_code', None)
    context = getattr(error, 'context', None)
    if raw_code is None and isinstance(context, dict):
        candidate = context.get('raw_code')
        if type(candidate) is int or isinstance(candidate, str) and candidate.isascii() and candidate.isdigit():
            raw_code = candidate
    code = raw_code or getattr(error, 'code', None)
    if isinstance(code, Enum):
        code = code.value
    code = str(code or 'sdk_error')
    if not re.fullmatch(r'[A-Za-z0-9_:-]{1,60}', code):
        code = 'sdk_error'
    lowered = code.lower()
    if code == '99991672' and operation in ('upload_media', 'download_resource'):
        message = '飞书权限不足，需要 im:resource（获取与上传图片或文件资源）'
    elif code == '99991672' and operation in ('start_stream', 'update_stream', 'finish_stream'):
        message = '飞书权限不足，需要 cardkit:card:write（创建与更新卡片）'
    elif 'permission' in lowered or code in ('99991672', '99991679'):
        message = '飞书权限不足，请检查机器人权限和目标会话授权'
    elif 'rate' in lowered or code in ('99991400', '429'):
        message = '飞书请求过于频繁，请稍后检查处理结果'
    elif 'token' in lowered or 'credential' in lowered or code in ('10003', '10014', '10015'):
        message = '飞书应用凭据无效或已失效，请检查配置'
    elif 'connect' in lowered or 'timeout' in lowered:
        message = '飞书连接失败或超时，请检查网络；在途发送结果可能不确定'
    else:
        message = '飞书操作失败，请检查应用凭据、飞书权限和网络'
    return {'code': 'feishu_' + code, 'error': message + '（' + code + '）'}


class SDKFailure(Exception):
    def __init__(self, error):
        self.code = getattr(error, 'code', 'send_failed')
        self.raw_code = getattr(error, 'raw_code', None)


def send_result(result):
    if not result.success:
        raise result.error if isinstance(result.error, Exception) else SDKFailure(result.error)
    response = {'success': True, 'messageId': result.message_id or ''}
    raw = getattr(result, 'raw', None)
    if isinstance(raw, dict) and isinstance(raw.get('data'), dict) and raw['data'].get('chat_id'):
        response['chatId'] = raw['data']['chat_id']
    if isinstance(raw, dict) and isinstance(raw.get('data'), dict):
        data = raw['data']
        body = data.get('body')
        if isinstance(body, dict) and isinstance(body.get('content'), str) and isinstance(data.get('msg_type'), str):
            from lark_channel.channel.normalize.registry import parse_message_content
            from lark_channel.channel.normalize.flatten import flatten
            response['messageType'] = data['msg_type']
            content = parse_message_content(data['msg_type'], body['content'])
            response['canonicalContent'] = json_value(content)
            _, resources = flatten(content)
            response['resources'] = json_value(resources)
    if getattr(result, 'chunk_ids', None):
        response['chunkIds'] = result.chunk_ids
    return response


class SDKSession:
    def __init__(self, emit, channel_factory=None):
        if channel_factory is None:
            from lark_channel import FeishuChannel
            channel_factory = FeishuChannel
        self.factory = channel_factory
        self.emit = emit
        self.channel = None
        self.registration_task = None
        self.registration_epoch = None

    async def handle(self, operation, params):
        if operation == 'chat_entry':
            from .chat import chat_entry
            return chat_entry(params['appId'])
        if operation == 'registration_start':
            from .registration import run_registration
            await self.cancel_registration()
            epoch = self.registration_epoch = object()
            def emit(payload):
                if self.registration_epoch is epoch:
                    self.emit('registration', payload)
            self.registration_task = asyncio.create_task(run_registration(emit, params.get('name', '飞书机器人')))
            return {'started': True}
        if operation == 'registration_cancel':
            await self.cancel_registration()
            return {'cancelled': True}
        if operation == 'connect':
            await self.close()
            from lark_channel import LogLevel
            channel = self.factory(app_id=params['appId'], app_secret=params['secret'], log_level=LogLevel.ERROR)
            self.channel = channel
            async def message(msg):
                if self.channel is channel:
                    self.emit('message', dict(messageId=msg.message_id, chatId=msg.chat_id,
                        sender=msg.sender_name or msg.sender_id, text=msg.content_text,
                        createdAt=msg.create_time, direction='inbound', senderId=msg.sender_id,
                        chatType=msg.chat_type, threadId=msg.conversation.thread_id,
                        replyMessageId=msg.reply_to_message_id, messageType=msg.raw_content_type,
                        mentions=json_value(msg.mentions), resources=json_value(msg.resources),
                        normalized=json_value(msg)))
            async def card_action(event):
                if self.channel is channel:
                    self.emit('card_action', dict(messageId=event.message_id, chatId=event.chat_id,
                        operator=getattr(event.operator, 'open_id', ''),
                        action=json_value(event.action)))
            async def error(_error):
                if self.channel is channel:
                    self.emit('connection', {'lastError': safe_error(_error)['error']})
            channel.on('message', message)
            channel.on('cardAction', card_action)
            channel.on('error', error)
            async def reconnecting(*_):
                if self.channel is channel:
                    self.emit('connection', {'connectionState': 'connecting'})
            async def reconnected(*_):
                if self.channel is channel:
                    self.emit('connection', {'connectionState': 'connected'})
            channel.on('reconnecting', reconnecting)
            channel.on('reconnected', reconnected)
            await channel.start_background(timeout=25)
            return {'connectionState': 'connected'}
        if operation == 'disconnect':
            await self.close()
            return {'connectionState': 'disconnected'}
        if self.channel is None:
            raise RuntimeError('not_connected')
        if operation in ('send', 'send_card'):
            if operation == 'send_card':
                target = params['chatId']
                message = {'card': params['card']}
                opts = {'receive_id_type': 'chat_id', 'uuid': params.get('requestId')}
            else:
                target = params['targetId']
                message = params['message']
                opts = {'receive_id_type': params['receiveIdType'], 'uuid': params.get('requestId')}
            if params.get('replyMessageId'):
                opts['reply_to'] = params['replyMessageId']
            if params.get('replyInThread') is not None:
                opts['reply_in_thread'] = params['replyInThread']
            result = await self.channel.send(target, message, opts)
            return send_result(result)
        if operation == 'update_card':
            return send_result(await self.channel.update_card(params['messageId'], params['card']))
        if operation == 'upload_media':
            from lark_channel.channel.types import MediaSource
            key = await self.channel.upload_media(MediaSource(kind='file', path=params['filePath']),
                kind=params['kind'], file_name=params.get('fileName'), file_type=params.get('fileType'))
            return {'mediaKey': key, 'kind': params['kind']}
        if operation == 'download_resource':
            path = await self.channel.download_resource_to_file(params['fileKey'],
                resource_type=params['resourceType'], message_id=params.get('messageId'),
                dest_dir=Path(params['destDir']), file_name=params.get('fileName'))
            return {'path': str(path), 'name': path.name, 'size': path.stat().st_size}
        if operation == 'start_stream':
            element_id = 'content'
            spec = {'schema': '2.0', 'config': {'streaming_mode': True, 'summary': {'content': ''}},
                    'body': {'elements': [{'tag': 'markdown', 'element_id': element_id, 'content': params['text']}]}}
            if params.get('title'):
                spec['header'] = {'title': {'tag': 'plain_text', 'content': params['title']}}
            card_id = await self.channel.create_card_instance(spec)
            result = await self.channel.send_card_by_reference(params['targetId'], card_id,
                receive_id_type=params['receiveIdType'], reply_to=params.get('replyMessageId'),
                reply_in_thread=params.get('replyInThread'))
            sent = send_result(result)
            if not sent['messageId']:
                raise SDKFailure(None)
            return {**sent, 'cardId': card_id, 'elementId': element_id, 'sequence': 0}
        if operation == 'update_stream':
            await self.channel.update_card_element_content(params['cardId'], params['elementId'],
                params['text'], params['sequence'])
            return {'success': True}
        if operation == 'finish_stream':
            await self.channel.finish_streaming_card(params['cardId'], params['sequence'])
            return {'success': True}
        raise ValueError('unknown_operation')

    async def cancel_registration(self):
        self.registration_epoch = None
        task, self.registration_task = self.registration_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self):
        await self.cancel_registration()
        channel, self.channel = self.channel, None
        if channel is not None:
            await channel.disconnect()


async def main(session):
    protocol = sys.stdout
    sys.stdout = open(os.devnull, 'w')  # SDK diagnostics can never enter JSON IPC.
    logging.disable(logging.CRITICAL)
    output_lock = threading.Lock()
    def write(value):
        with output_lock:
            protocol.write(json.dumps(value, ensure_ascii=False) + '\n')
            protocol.flush()
    session.emit = lambda event, payload: write({'event': event, 'payload': payload})
    incoming = queue.Queue()
    def read_input():
        for line in sys.stdin:
            incoming.put(line)
        incoming.put(None)
    threading.Thread(target=read_input, daemon=True, name='feishu-stdin').start()
    try:
        while True:
            try:
                line = incoming.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if line is None:
                break
            request = json.loads(line)
            try:
                result = await session.handle(request['operation'], request.get('params', {}))
                write({'id': request['id'], 'result': result})
            except Exception as error:
                # Only a constrained SDK code crosses IPC; never exception text or HTTP bodies.
                write(dict(id=request['id'], **safe_error(error, request['operation'])))
    finally:
        await session.close()


if __name__ == '__main__':
    # Import the SDK before starting our control loop: its WS module captures
    # a process-global loop which must remain separate from this running loop.
    session = SDKSession(lambda *_: None)
    try:
        asyncio.run(main(session))
    finally:
        from lark_channel.ws.client import loop as ws_loop
        if not ws_loop.is_running() and not ws_loop.is_closed():
            ws_loop.close()
        registration_ws = sys.modules.get('lark_oapi.ws.client')
        registration_loop = getattr(registration_ws, 'loop', None)
        if registration_loop is not None and not registration_loop.is_running() and not registration_loop.is_closed():
            registration_loop.close()
