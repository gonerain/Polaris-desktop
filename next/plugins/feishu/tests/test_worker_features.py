import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from polaris_feishu_bot.worker import SDKSession, SDKFailure, json_value, safe_error


def ok(**kwargs):
    return SimpleNamespace(success=True, message_id='om_real', chunk_ids=None, raw=kwargs, error=None)


class WorkerFeatures(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = SDKSession(lambda *_: None, channel_factory=lambda **_: None)
        self.channel = self.session.channel = SimpleNamespace(
            send=AsyncMock(return_value=ok(data={'chat_id': 'oc_real'})),
            upload_media=AsyncMock(return_value='file_real'),
            download_resource_to_file=AsyncMock(),
            create_card_instance=AsyncMock(return_value='card_real'),
            send_card_by_reference=AsyncMock(return_value=ok()),
            update_card_element_content=AsyncMock(), finish_streaming_card=AsyncMock())

    async def test_send_target_thread_and_failure(self):
        p = {'targetId': 'ou_user', 'receiveIdType': 'open_id', 'message': {'text': 'hi'},
             'replyMessageId': 'om_parent', 'replyInThread': True, 'requestId': 'req'}
        self.assertEqual(await self.session.handle('send', p), {'success': True, 'messageId': 'om_real', 'chatId': 'oc_real'})
        self.channel.send.assert_awaited_once_with('ou_user', {'text': 'hi'},
            {'receive_id_type': 'open_id', 'uuid': 'req', 'reply_to': 'om_parent', 'reply_in_thread': True})
        self.channel.send.return_value = SimpleNamespace(success=False, error=SimpleNamespace(code='failed', raw_code=123))
        with self.assertRaises(SDKFailure) as error:
            await self.session.handle('send', p)
        self.assertEqual(error.exception.raw_code, 123)

    async def test_media(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'a.txt'
            path.write_bytes(b'abc')
            result = await self.session.handle('upload_media', {'filePath': str(path), 'kind': 'file', 'fileName': 'a.txt'})
            self.assertEqual(result, {'mediaKey': 'file_real', 'kind': 'file'})
            args, kwargs = self.channel.upload_media.await_args
            self.assertEqual((args[0].kind, args[0].path, kwargs['kind']), ('file', str(path), 'file'))
            self.channel.download_resource_to_file.return_value = path
            result = await self.session.handle('download_resource', {'fileKey':'file_real', 'messageId':'om_real', 'resourceType':'file', 'destDir':directory})
            self.assertEqual(result, {'path': str(path), 'name':'a.txt', 'size':3})

    async def test_stream_steps_and_missing_message(self):
        p = {'targetId':'oc_chat', 'receiveIdType':'chat_id', 'text':'start', 'title':'Title', 'replyInThread':True}
        started = await self.session.handle('start_stream', p)
        self.assertEqual(started, {'success':True, 'messageId':'om_real', 'cardId':'card_real', 'elementId':'content', 'sequence':0})
        spec = self.channel.create_card_instance.await_args.args[0]
        self.assertTrue(spec['config']['streaming_mode'])
        self.assertEqual(spec['body']['elements'][0]['element_id'], 'content')
        await self.session.handle('update_stream', {'cardId':'card_real', 'elementId':'content', 'text':'full', 'sequence':1})
        await self.session.handle('finish_stream', {'cardId':'card_real', 'sequence':2})
        self.channel.update_card_element_content.assert_awaited_once_with('card_real', 'content', 'full', 1)
        self.channel.finish_streaming_card.assert_awaited_once_with('card_real', 2)
        self.channel.send_card_by_reference.return_value.message_id = None
        with self.assertRaises(SDKFailure):
            await self.session.handle('start_stream', p)

    def test_normalized_removes_raw_recursively(self):
        from dataclasses import dataclass
        @dataclass
        class Message:
            content: dict
            raw: dict
        self.assertEqual(json_value(Message({'kind':'image', 'raw':{'secret':1}}, {'secret':2})), {'content':{'kind':'image'}})

    def test_permission_messages_are_operation_specific(self):
        error = SDKFailure(SimpleNamespace(code='failed', raw_code=99991672))
        for operation in ('upload_media', 'download_resource'):
            result = safe_error(error, operation)
            self.assertEqual(result['code'], 'feishu_99991672')
            self.assertIn('im:resource', result['error'])
        for operation in ('start_stream', 'update_stream', 'finish_stream'):
            self.assertIn('cardkit:card:write', safe_error(error, operation)['error'])
        self.assertNotIn('im:resource', safe_error(RuntimeError('network'), 'upload_media')['error'])

    def test_real_upload_error_keeps_safe_raw_code(self):
        from lark_channel.channel.errors import FeishuChannelError, FeishuChannelErrorCode
        error = FeishuChannelError(FeishuChannelErrorCode.UPLOAD_FAILED, 'sensitive-message',
            context={'raw_code': 99991672, 'raw_msg': 'sensitive-url'})
        result = safe_error(error, 'upload_media')
        self.assertEqual(result['code'], 'feishu_99991672')
        self.assertIn('im:resource', result['error'])
        self.assertNotIn('sensitive', str(result))

    def test_send_canonical_resources_from_server(self):
        import json
        from polaris_feishu_bot.worker import send_result
        fixture = {'data': {'msg_type': 'file', 'body': {'content': json.dumps(
            {'file_key': 'file_message_key', 'file_name': 'a.txt'})}}}
        result = send_result(ok(**fixture))
        self.assertEqual(result['resources'][0]['file_key'], 'file_message_key')
        self.assertNotEqual(result['resources'][0]['file_key'], 'file_upload_key')
        self.assertEqual(result['canonicalContent']['kind'], 'file')
        self.assertEqual(result['messageType'], 'file')
        for kind, body, key in [
            ('image', {'image_key':'img_message'}, 'img_message'),
            ('audio', {'file_key':'file_audio'}, 'file_audio'),
            ('media', {'file_key':'file_video'}, 'file_video'),
            ('post', {'zh_cn': {'title':'', 'content': [[{'tag':'img','image_key':'img_post'}]]}}, 'img_post'),
        ]:
            fixture = {'data': {'msg_type':kind, 'body':{'content':json.dumps(body)}}}
            result = send_result(ok(**fixture))
            self.assertEqual(result['resources'][0]['file_key'], key)
            self.assertEqual(result['messageType'], kind)
        self.assertNotIn('resources', send_result(ok()))
