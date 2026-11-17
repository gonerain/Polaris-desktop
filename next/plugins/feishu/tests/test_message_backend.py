"""Public first-batch messaging contracts, without network delivery."""
import base64
import inspect
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from polaris_feishu_bot import FeishuBot
from polaris_feishu_bot.store import Store
from polaris_platform.protocol import PlatformError


class Transport:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.fail = None
    def request(self, operation, params):
        self.calls.append((operation, params))
        if self.fail:
            raise self.fail
        if operation == 'connect':
            return {'connectionState': 'connected'}
        if operation == 'upload_media':
            self.uploaded = Path(params['filePath']).read_bytes()
            return {'mediaKey': 'img_test' if params['kind'] == 'image' else 'file_test', 'kind': params['kind']}
        if operation == 'download_resource':
            path = Path(params['destDir']) / (params['fileName'] or 'received.bin')
            path.write_bytes(b'downloaded-file')
            return {'path': str(path), 'name': path.name, 'size': path.stat().st_size}
        if operation == 'start_stream':
            return dict(success=True, cardId='card-one', messageId='stream-message', elementId='content', sequence=0)
        return dict(success=True, messageId='out-' + str(len(self.calls)))
    def close(self):
        pass


class MessageBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
    def bot(self, identity='one'):
        bot = FeishuBot(dict(instanceId=identity, dataDir=str(Path(self.temp.name) / identity)), Transport)
        bot.start(SimpleNamespace(id=identity))
        bot.store.configure(dict(instanceName=identity, appId='cli_' + identity, secret='fake', desiredConnected=False))
        bot._connect()
        self.addCleanup(bot.stop)
        return bot

    def test_old_send_targeted_media_and_thread_reply_keep_real_routing(self):
        bot = self.bot()
        bot.send('chat-one', 'legacy')
        bot.upload_media('eA==', 'image.png', kind='image')
        bot.send(target_id='person-one', target_type='open_id', message={'image': {'source': 'img_test'}})
        args = bot._transport.calls[-1][1]
        self.assertEqual((args['targetId'], args['receiveIdType']), ('person-one', 'open_id'))
        media = bot.read_messages()['items'][-1]
        self.assertEqual(media['chatId'], '')
        self.assertEqual(media['targetId'], 'person-one')
        self.assertEqual(media['content'], {'image': {'source': 'img_test'}})
        bot.store.append('message', dict(messageId='in-topic', chatId='chat-one', threadId='topic-one', text='hi',
            normalized={'content': {'kind': 'text', 'text': 'hi'}, 'conversation': {'chat_id': 'chat-one', 'thread_id': 'topic-one'}, 'resources': [{'file_key': 'resource-key'}]}))
        bot.reply('in-topic', message={'markdown': '**reply**'})
        self.assertTrue(bot._transport.calls[-1][1]['replyInThread'])
        bot.reply('in-topic', 'flat override', reply_in_thread=False)
        self.assertFalse(bot._transport.calls[-1][1]['replyInThread'])
        self.assertEqual(bot.store.message('in-topic')['normalized']['resources'][0]['file_key'], 'resource-key')
        with self.assertRaises(PlatformError):
            bot.send('wrong-chat', 'no', reply_message_id='in-topic')
        with self.assertRaises(PlatformError):
            self.bot('two').reply('in-topic', 'no')

    def test_attachments_roundtrip_chunks_and_instance_boundary(self):
        one, two = self.bot(), self.bot('two')
        data = b'file-content\x00\xff'
        uploaded = one.upload_media(base64.b64encode(data).decode(), 'example.bin')
        self.assertEqual(uploaded['media_key'], 'file_test')
        self.assertEqual(one._transport.uploaded, data)
        first = one.read_attachment(uploaded['file_id'], limit=4)
        second = one.read_attachment(uploaded['file_id'], offset=first['nextOffset'])
        self.assertEqual(base64.b64decode(first['data_base64']) + base64.b64decode(second['data_base64']), data)
        self.assertTrue(second['eof'])
        for source in ['/home/ning/private', 'https://example.com/image', 'img_not_owned']:
            with self.assertRaises(PlatformError):
                one.send('chat-one', message={'image': {'source': source}})
        with self.assertRaises(PlatformError):
            two.send('chat-two', message={'file': {'source': uploaded['media_key']}})
        with self.assertRaises(PlatformError):
            two.read_attachment(uploaded['file_id'])
        for name in ['../configuration.json', 'folder\\secret', 'bad' + chr(0)]:
            with self.assertRaises(PlatformError):
                one.upload_media('eA==', name)
        downloaded = one.download_resource('resource-key', message_id='message', resource_type='file')
        self.assertEqual(base64.b64decode(one.read_attachment(downloaded['file_id'])['data_base64']), b'downloaded-file')
        one.download_resource('audio-key', resource_type='audio')
        self.assertEqual(one._transport.calls[-1][1]['resourceType'], 'file')
        self.assertTrue(Path(downloaded['path']).is_relative_to(one.store.attachment_directory))
        self.assertEqual(Path(downloaded['path']).stat().st_mode & 0o777, 0o600)

    def test_sent_attachment_records_message_resource_key_instead_of_upload_key(self):
        bot = self.bot()
        uploaded = bot.upload_media('dGVzdC1maWxl', 'example.txt', kind='file')
        upload_key = uploaded['media_key']
        canonical_key = 'file_message_resource_B'
        response = dict(success=True, messageId='sent-file-message', chatId='chat-one',
                        canonicalContent={'file_key': canonical_key, 'file_name': 'example.txt'},
                        resources=[dict(type='file', file_key=canonical_key, file_name='example.txt')])
        original_request = bot._transport.request
        def request(operation, params):
            result = original_request(operation, params)
            return response if operation == 'send' else result
        with patch.object(bot._transport, 'request', side_effect=request):
            bot.send('chat-one', message={'file': {'source': upload_key}})
        self.assertEqual(bot._transport.calls[-1][1]['message']['file']['source'], upload_key)
        record = bot.read_messages()['items'][-1]
        self.assertNotEqual(upload_key, canonical_key)
        self.assertEqual(record['resources'][0]['file_key'], canonical_key)
        self.assertEqual(record['canonicalContent']['file_key'], canonical_key)
        bot.download_resource(record['resources'][0]['file_key'], message_id=record['messageId'], resource_type='file')
        operation, params = bot._transport.calls[-1]
        self.assertEqual((operation, params['fileKey'], params['messageId']),
                         ('download_resource', canonical_key, 'sent-file-message'))
        response['resources'][0]['file_key'] = 'later-mutation'
        self.assertEqual(bot.store.message('sent-file-message')['resources'][0]['file_key'], canonical_key)
        image = bot.upload_media('aW1hZ2U=', 'image.png', kind='image')
        response.update(messageId='sent-caption-image', messageType='post',
                        canonicalContent={'kind': 'post', 'text': 'caption'},
                        resources=[dict(type='image', file_key='img_message_resource_B')])
        with patch.object(bot._transport, 'request', side_effect=request):
            bot.send('chat-one', message={'image': {'source': image['media_key']}, 'caption': 'caption'})
        record = bot.store.message('sent-caption-image')
        self.assertEqual(record['messageType'], 'post')
        self.assertEqual(record['resources'][0]['file_key'], 'img_message_resource_B')

    def test_server_interactive_card_type_remains_updatable(self):
        bot = self.bot()
        original = bot._transport.request
        def request(operation, params):
            result = original(operation, params)
            if operation == 'send':
                result['messageType'] = 'interactive'
            return result
        with patch.object(bot._transport, 'request', side_effect=request):
            sent = bot.send('chat-one', message={'card': {'schema': '2.0', 'body': {'elements': []}}})
        self.assertEqual(bot.store.message(sent['messageId'])['messageType'], 'interactive')
        self.assertTrue(bot.update_card(sent['messageId'], {'schema': '2.0', 'body': {'elements': []}})['success'])
        self.assertEqual(bot._transport.calls[-1][0], 'update_card')
        bot.store.append('message', dict(messageId='legacy-card', chatId='chat-one', direction='outbound', messageType='card'))
        self.assertTrue(bot.update_card('legacy-card', {})['success'])

    def test_stream_sequence_failure_restart_and_latest_message_are_persistent(self):
        one, two = self.bot(), self.bot('two')
        started = one.start_stream('chat-one', text='start', title='Title')
        sid = started['stream_id']
        initial = one.read_messages()['nextCursor']
        one.update_stream(sid, 'partial')
        self.assertEqual(one._transport.calls[-1][1]['sequence'], 1)
        self.assertEqual(one.read_messages(after=initial)['items'][0]['text'], 'partial')
        one._transport.fail = PlatformError('feishu_failed', 'upstream failed')
        with self.assertRaises(PlatformError):
            one.update_stream(sid, 'unknown result')
        self.assertEqual(one._transport.calls[-1][1]['sequence'], 2)
        self.assertEqual(one.status()['activeStreams'][0]['text'], 'partial')
        with self.assertRaises(PlatformError):
            two.update_stream(sid, 'wrong instance')
        one._transport.fail = None
        one.store = Store(one.store.directory)
        self.assertEqual(one.status()['activeStreams'][0]['stream_id'], sid)
        one.finish_stream(sid, text='final')
        calls = one._transport.calls[-2:]
        self.assertEqual([(op, p['sequence']) for op, p in calls], [('update_stream', 3), ('finish_stream', 4)])
        self.assertEqual(one.status()['activeStreams'], [])
        row = one.store.message(started['message_id'])
        self.assertEqual((row['text'], row['streamState']), ('final', 'finished'))
        with self.assertRaises(PlatformError):
            one.update_stream(sid, 'late')

    def test_missing_stream_message_is_an_explicit_contract_error(self):
        bot = self.bot()
        started = bot.start_stream('chat-one')
        with bot.store.database() as db:
            db.execute('DELETE FROM records WHERE identity=?', (started['message_id'],))
        with self.assertRaises(PlatformError) as error:
            bot.update_stream(started['stream_id'], 'new')
        self.assertEqual(error.exception.code, 'stream_message_missing')

    def test_public_help_lists_real_parameters_and_preserves_instance_binding(self):
        bot = self.bot()
        description = bot.describe()
        names = ['status', 'read_messages', 'read_card_actions', 'send', 'reply', 'send_card', 'update_card',
                 'upload_media', 'download_resource', 'read_attachment', 'start_stream', 'update_stream', 'finish_stream']
        for name in names:
            with self.subTest(operation=name):
                help = description['operations'][name]
                self.assertEqual(help['applicationBinding'], 'instance')
                self.assertTrue(help['title'])
                self.assertTrue(help['description'])
                signature = inspect.signature(getattr(bot, name))
                self.assertEqual(set(help['parameters']['properties']), set(signature.parameters))
        self.assertTrue(description['operations']['configure']['humanOnly'])
        self.assertFalse(description['operations']['configure']['modelCallable'])


if __name__ == '__main__':
    unittest.main()
