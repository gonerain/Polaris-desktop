"""Parameter help for the component's public instance operations."""
from copy import deepcopy

S = {'type': 'string'}
TARGET = dict(chat_id=dict(S, description='会话 ID；与 target_id 二选一'),
              target_id=dict(S, description='明确接收目标；与 chat_id 二选一'),
              target_type={'type': 'string', 'enum': ['chat_id', 'open_id', 'user_id', 'union_id', 'email'], 'default': 'chat_id'})
REPLY = dict(reply_message_id=dict(S, description='当前实例当前会话已有消息 ID'),
             reply_in_thread={'type': 'boolean', 'description': '是否在话题内回复；省略时跟随引用消息'})
MESSAGE = {'type': 'object', 'description': 'SDK 出站消息：text/markdown/post/card/image/file/audio/video/share_chat/share_user/sticker。附件示例 {"image":{"source":"img_..."}} 或 {"file":{"source":"file_..."}}。媒体 source 必须为当前实例 upload_media 返回的对应 img_/file_ 资源键，不接受本地路径或 URL。', 'additionalProperties': True}
READ = dict(after={'type': 'integer', 'minimum': 0, 'default': 0},
            limit={'type': 'integer', 'minimum': 1, 'maximum': 500, 'default': 100}, chat_id=S)
ENTRIES = {
    'status': ('查看机器人状态', '本地配置和连接状态；activeStreams 为当前实例尚未完成的流式卡片，含 stream_id/message_id/text/state。', {}, []),
    'read_messages': ('读取本地消息', '读取本实例实际接收或发送成功的本地记录，不拉取远端历史。返回 items/nextCursor；入站 normalized 保留完整规范化结构，不含 raw；流式更新推进游标。', READ, []),
    'read_card_actions': ('读取卡片交互', '按独立消费者游标读取本实例保存的卡片操作，返回 items/nextCursor。', READ, []),
    'send': ('发送消息', '目标 chat_id/target_id 二选一；text/message 二选一。返回 success/messageId，可含 chunkIds/chatId。真实发送，不自动重试。', dict(TARGET, **REPLY, text=S, message=MESSAGE), []),
    'reply': ('引用回复', '引用本实例已有消息；text/message 二选一，默认跟随原消息话题。', dict(message_id=S, text=S, message=MESSAGE, reply_in_thread=REPLY['reply_in_thread']), ['message_id']),
    'send_card': ('发送卡片', '向指定会话发送卡片 JSON，返回 success/messageId。', dict(chat_id=S, card={'type': 'object'}), ['chat_id', 'card']),
    'update_card': ('更新卡片', '更新当前实例已发送的卡片消息 JSON。', dict(message_id=S, card={'type': 'object'}), ['message_id', 'card']),
    'upload_media': ('上传附件', 'base64 解码保存于当前实例附件目录，再上传飞书。返回 media_key/kind/file_id/path/name/size；上传不会发送消息。', dict(data_base64=dict(S, description='文件内容的标准 base64'), file_name=dict(S, description='不含路径的文件名'), kind={'type': 'string', 'enum': ['image', 'file'], 'default': 'file'}, file_type=dict(S, description='SDK 上传文件类型；音频通常 opus、视频 mp4')), ['data_base64', 'file_name']),
    'download_resource': ('下载消息附件', '从飞书下载到当前实例附件目录，返回 file_id/path/name/size；API 可用 read_attachment 分段读取内容。', dict(file_key=S, message_id=S, resource_type={'type': 'string', 'enum': ['image', 'file', 'audio', 'video'], 'default': 'image'}, file_name=dict(S, description='可选不含路径的文件名')), ['file_key']),
    'read_attachment': ('读取附件内容', '仅读取当前实例持有的 file_id；返回 data_base64/offset/nextOffset/eof/name/size，分块读取不改变文件。', dict(file_id=S, offset={'type': 'integer', 'minimum': 0, 'default': 0}, limit={'type': 'integer', 'minimum': 1, 'maximum': 1048576, 'default': 262144}), ['file_id']),
    'start_stream': ('开始流式卡片', '真实创建并发送标准 Markdown 流式卡片；返回 success/stream_id/card_id/message_id。后续分次调用 update_stream/finish_stream，不自动完成。', dict(TARGET, **REPLY, text=dict(S, default=''), title=dict(S, default='')), []),
    'update_stream': ('更新流式卡片', 'text 是当前完整 Markdown 正文；成功后保存最新正文。每次请求消耗一个递增序号，失败不自动重发。', dict(stream_id=S, text=S), ['stream_id', 'text']),
    'finish_stream': ('完成流式卡片', '可先用 text 写最后正文，再关闭流式状态；成功后不能继续 update。失败可查本地状态，不自动重试或结束。', dict(stream_id=S, text=S), ['stream_id']),
}


def public_help():
    result = {}
    for name, (title, description, properties, required) in ENTRIES.items():
        schema = dict(type='object', properties=deepcopy(properties), required=required, additionalProperties=False)
        choices = []
        if name in ('send', 'start_stream'):
            choices.append({'oneOf': [{'required': ['chat_id'], 'not': {'required': ['target_id']}}, {'required': ['target_id'], 'not': {'required': ['chat_id']}}]})
        if name in ('send', 'reply'):
            choices.append({'oneOf': [{'required': ['text'], 'not': {'required': ['message']}}, {'required': ['message'], 'not': {'required': ['text']}}]})
        if choices:
            schema['allOf'] = choices
        result[name] = dict(title=title, description=description, parameters=schema)
    return result
