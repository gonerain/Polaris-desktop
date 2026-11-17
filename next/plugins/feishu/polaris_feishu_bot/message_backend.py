"""Instance-owned message, attachment and incremental card operations."""
from copy import deepcopy
import base64
import binascii
import json
from pathlib import Path
from uuid import uuid4
from polaris_platform.protocol import PlatformError


class MessageBackend:
    def _network_request(self, operation, params):
        with self._network_lock:
            self._check()
            with self._lock:
                transport, generation = self._transport, self._generation
                if transport is None or self._state != 'connected':
                    raise PlatformError('not_connected', '请先连接飞书机器人')
            try:
                result = transport.request(operation, params)
            except PlatformError as error:
                if error.code in ('feishu_timeout', 'feishu_disconnected'):
                    with self._lock:
                        if generation == self._generation:
                            self._state, self._error = 'error', error.message
                raise
            with self._lock:
                self._check()
                if generation != self._generation:
                    raise PlatformError('stale_instance', '操作所属连接已关闭')
            return result

    def _target(self, chat_id, target_id, target_type):
        if (chat_id is None) == (target_id is None):
            raise PlatformError('invalid_params', 'chat_id 与 target_id 必须且只能提供一个')
        if target_type not in ('chat_id', 'open_id', 'user_id', 'union_id', 'email'):
            raise PlatformError('invalid_params', '目标 ID 类型无效')
        if chat_id is not None and target_type != 'chat_id':
            raise PlatformError('invalid_params', 'chat_id 只能使用 chat_id 目标类型')
        return self._text(chat_id if chat_id is not None else target_id, '接收目标', 200), target_type

    def _outbound(self, text, message):
        if (text is None) == (message is None):
            raise PlatformError('invalid_params', 'text 与 message 必须且只能提供一个')
        if text is not None:
            if not isinstance(text, str) or not text.strip():
                raise PlatformError('invalid_params', '消息内容不能为空')
            return {'text': text}
        try:
            if not isinstance(message, dict):
                raise ValueError()
            json.dumps(message, allow_nan=False)
        except (TypeError, ValueError):
            raise PlatformError('invalid_params', 'message 须为有效 JSON 对象') from None
        for media_type in ('image', 'file', 'audio', 'video'):
            if media_type in message:
                spec = message[media_type]
                source = spec.get('source') if isinstance(spec, dict) else None
                kind = 'image' if media_type == 'image' else 'file'
                prefix = 'img_' if kind == 'image' else 'file_'
                if not isinstance(source, str) or not source.startswith(prefix) or not self.store.owns_media_key(source, kind):
                    raise PlatformError('invalid_media_source', '附件 source 须为当前实例 upload_media 返回的对应资源键，不接受路径或 URL')
        return deepcopy(message)

    def _reply_options(self, target_id, target_type, reply_message_id, reply_in_thread):
        if reply_in_thread is not None and type(reply_in_thread) is not bool:
            raise PlatformError('invalid_params', 'reply_in_thread 须为布尔值')
        if reply_message_id:
            known = self.store.message(reply_message_id)
            if known is None or target_type != 'chat_id' or known['chatId'] != target_id:
                raise PlatformError('invalid_reply', '引用回复须指向当前实例当前会话中已有的消息')
            if reply_in_thread is None:
                reply_in_thread = bool(known.get('threadId') or known.get('normalized', {}).get('conversation', {}).get('thread_id'))
        return dict(replyMessageId=reply_message_id, replyInThread=reply_in_thread)

    def _record_outbound(self, result, target_id, target_type, message, options):
        kind = next((key for key in ('text', 'markdown', 'post', 'card', 'image', 'file', 'audio', 'video', 'share_chat', 'share_user', 'sticker') if key in message), 'unknown')
        chat_id = result.get('chatId') or (target_id if target_type == 'chat_id' else '')
        text = message.get('text') or message.get('markdown') or ('[卡片]' if kind == 'card' else '[' + kind + ']')
        record = dict(messageId=result['messageId'], chatId=chat_id,
            targetId=target_id, targetType=target_type, sender='机器人', text=text,
            direction='outbound', messageType=result.get('messageType') or ('post' if kind == 'markdown' else kind),
            content=deepcopy(message), replyMessageId=options.get('replyMessageId') or '',
            replyInThread=options.get('replyInThread'), chunkIds=result.get('chunkIds') or [])
        for field in ('canonicalContent', 'resources'):
            if field in result:
                record[field] = deepcopy(result[field])
        self.store.append('message', record)

    def send(self, chat_id=None, text=None, reply_message_id=None, *, target_id=None,
             target_type='chat_id', message=None, reply_in_thread=None):
        target_id, target_type = self._target(chat_id, target_id, target_type)
        content = self._outbound(text, message)
        options = self._reply_options(target_id, target_type, reply_message_id, reply_in_thread)
        with self._network_lock:
            result = self._network_request('send', dict(targetId=target_id, receiveIdType=target_type,
                message=content, requestId=uuid4().hex, **options))
            self._record_outbound(result, target_id, target_type, content, options)
            return result

    def reply(self, message_id, text=None, *, message=None, reply_in_thread=None):
        message_id = self._text(message_id, '消息标识', 200)
        known = self.store.message(message_id)
        if known is None:
            raise PlatformError('message_missing', '当前实例没有这条消息')
        return self.send(known['chatId'], text, message_id, message=message, reply_in_thread=reply_in_thread)

    def upload_media(self, data_base64, file_name, kind='file', file_type=None):
        self._check()
        if kind not in ('image', 'file'):
            raise PlatformError('invalid_params', 'kind 须为 image 或 file')
        if file_type is not None and not isinstance(file_type, str):
            raise PlatformError('invalid_params', 'file_type 须为字符串')
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise PlatformError('invalid_params', '附件内容须为有效 base64') from None
        attachment = self.store.save_attachment(data, file_name)
        result = self._network_request('upload_media', dict(filePath=attachment['path'], kind=kind,
            fileName=attachment['name'], fileType=file_type))
        self.store.record_media_key(attachment['file_id'], result['mediaKey'], kind)
        return dict(attachment, media_key=result['mediaKey'], kind=kind)

    def download_resource(self, file_key, message_id=None, resource_type='image', file_name=None):
        self._check()
        file_key = self._text(file_key, '资源标识', 500)
        if resource_type not in ('image', 'file', 'audio', 'video'):
            raise PlatformError('invalid_params', '资源类型无效')
        if message_id is not None:
            message_id = self._text(message_id, '消息标识', 200)
        directory = self.store.attachment_directory / uuid4().hex
        directory.mkdir(mode=0o700)
        result = self._network_request('download_resource', dict(fileKey=file_key, messageId=message_id,
            resourceType='file' if resource_type in ('audio', 'video') else resource_type, destDir=str(directory), fileName=self.store.attachment_name(file_name) if file_name else None))
        return self.store.register_attachment(Path(result['path']), result.get('name'))

    def read_attachment(self, file_id, offset=0, limit=262144):
        self._check()
        file_id = self._text(file_id, '附件标识', 200)
        return self.store.read_attachment(file_id, offset, limit)

    def start_stream(self, chat_id=None, text='', title='', reply_message_id=None, *,
                     target_id=None, target_type='chat_id', reply_in_thread=None):
        target_id, target_type = self._target(chat_id, target_id, target_type)
        if not isinstance(text, str) or not isinstance(title, str):
            raise PlatformError('invalid_params', '流式卡片正文和标题须为字符串')
        options = self._reply_options(target_id, target_type, reply_message_id, reply_in_thread)
        with self._network_lock:
            result = self._network_request('start_stream', dict(targetId=target_id, receiveIdType=target_type,
                text=text, title=title, requestId=uuid4().hex, **options))
            stream_id = uuid4().hex
            state = dict(streamId=stream_id, cardId=result['cardId'], messageId=result['messageId'],
                elementId=result['elementId'], sequence=result['sequence'], state='open', text=text,
                title=title, chatId=result.get('chatId') or (target_id if target_type == 'chat_id' else ''), targetId=target_id, targetType=target_type, options=options)
            self.store.save_stream(state)
            self._record_outbound(result, target_id, target_type, {'card': {'text': text, 'title': title}}, options)
            self.store.update_stream_message(state)
            return dict(success=True, stream_id=stream_id, card_id=result['cardId'], message_id=result['messageId'])

    def update_stream(self, stream_id, text):
        self._check()
        stream_id = self._text(stream_id, '流式卡片标识', 200)
        if not isinstance(text, str):
            raise PlatformError('invalid_params', '流式正文须为字符串')
        with self._network_lock:
            state = self.store.reserve_stream_sequence(stream_id)
            result = self._network_request('update_stream', dict(cardId=state['cardId'],
                elementId=state['elementId'], text=text, sequence=state['sequence']))
            state['text'] = text
            self.store.save_stream(state)
            self.store.update_stream_message(state)
            return dict(result, stream_id=stream_id)

    def finish_stream(self, stream_id, text=None):
        self._check()
        stream_id = self._text(stream_id, '流式卡片标识', 200)
        if text is not None and not isinstance(text, str):
            raise PlatformError('invalid_params', '流式正文须为字符串')
        with self._network_lock:
            if text is not None:
                self.update_stream(stream_id, text)
            state = self.store.reserve_stream_sequence(stream_id)
            result = self._network_request('finish_stream', dict(cardId=state['cardId'], sequence=state['sequence']))
            state['state'] = 'finished'
            self.store.save_stream(state)
            self.store.update_stream_message(state)
            return dict(result, stream_id=stream_id)
