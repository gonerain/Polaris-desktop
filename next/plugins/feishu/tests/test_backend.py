import asyncio
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future
from unittest.mock import MagicMock
import time
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from polaris_feishu_bot import FeishuBot
from polaris_feishu_bot.store import Store
from polaris_feishu_bot.transport import WorkerTransport
from polaris_feishu_bot.worker import SDKSession, safe_error
from polaris_platform.protocol import PlatformError


class FakeTransport:
    def __init__(self, callback):
        self.callback, self.closed, self.calls = callback, False, []

    def request(self, operation, params):
        self.calls.append((operation, params))
        if operation == 'connect':
            return {'connectionState': 'connected'}
        return {'success': True, 'messageId': 'om_' + str(len(self.calls))}

    def close(self):
        self.closed = True


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def bot(self, name='one'):
        bot = FeishuBot({'instanceId': name, 'dataDir': str(Path(self.temp.name) / name)}, FakeTransport)
        bot.start(SimpleNamespace(id=name))
        self.addCleanup(bot.stop)
        return bot

    def test_two_credentials_storage_routing_stop_and_restart(self):
        one, two = self.bot(), self.bot('two')
        one.store.configure(dict(instanceName='One', appId='cli_one', secret='fake-one', desiredConnected=False))
        two.store.configure(dict(instanceName='Two', appId='cli_two', secret='fake-two', desiredConnected=False))
        one._connect()
        two._connect()
        first, second = one._transport, two._transport
        self.assertEqual(first.calls[0][1]['appId'], 'cli_one')
        self.assertEqual(second.calls[0][1]['appId'], 'cli_two')
        first.callback('message', dict(messageId='m1', chatId='c1', text='one', sender='u', direction='inbound'))
        second.callback('message', dict(messageId='m2', chatId='c2', text='two', sender='v', direction='inbound'))
        self.assertEqual([v['text'] for v in one.read_messages()['items']], ['one'])
        self.assertEqual([v['text'] for v in two.read_messages()['items']], ['two'])
        one.stop()
        first.callback('message', dict(messageId='late', chatId='c1', text='late'))
        self.assertEqual(two.send('c2', 'still works')['success'], True)
        one.start(SimpleNamespace(id='one'))
        self.assertEqual([v['text'] for v in one.read_messages()['items']], ['one'])
        self.assertEqual(one.status()['connectionState'], 'disconnected')
        self.assertNotIn('secret', json.dumps(one.status()).lower().replace('hassecret', ''))
        self.assertEqual((one.store.directory / 'configuration.json').stat().st_mode & 0o777, 0o600)

    def test_polling_cursors_duplicate_and_card_actions(self):
        bot = self.bot()
        for n in range(4):
            bot.store.append('message', dict(messageId=str(n), chatId='a' if n % 2 else 'b', text=str(n)))
        bot.store.append('message', dict(messageId='0', chatId='b', text='duplicate'))
        first = bot.read_messages(limit=2)
        self.assertEqual(len(first['items']), 2)
        self.assertEqual(bot.read_messages(limit=2), first)
        last = bot.read_messages(after=first['nextCursor'], limit=2)
        self.assertEqual([v['text'] for v in last['items']], ['2', '3'])
        self.assertEqual(bot.read_messages(after=last['nextCursor'])['nextCursor'], last['nextCursor'])
        self.assertEqual([v['text'] for v in bot.read_messages(chat_id='a')['items']], ['1', '3'])
        bot.store.append('card_action', dict(messageId='card', chatId='a', action={'form_value': {'x': 'y'}}))
        self.assertEqual(bot.read_card_actions()['items'][0]['action']['form_value'], {'x': 'y'})

    def test_config_identity_and_message_validation(self):
        bot = self.bot()
        bot.store.configure(dict(instanceName='One', appId='cli_one', secret='fake', desiredConnected=False))
        with patch.object(bot, '_human'):
            with self.assertRaises(PlatformError) as changed:
                bot.configure('One', 'cli_other', 'new', ctx=None)
            self.assertEqual(changed.exception.code, 'new_instance_required')
            bot.configure('Renamed', 'cli_one', '', ctx=None)
        self.assertEqual(bot.store.configuration()['secret'], 'fake')
        for value in [[], {'x': float('nan')}, {'x': object()}]:
            with self.assertRaises(PlatformError):
                bot._card(value)
        bot.store.append('message', dict(messageId='text', chatId='a', direction='outbound', messageType='text'))
        with self.assertRaises(PlatformError):
            bot.update_card('text', {})
        with self.assertRaises(PlatformError):
            bot.send('a', 'hello', 'unknown')

    def test_connection_intent_restore_without_send(self):
        bot = self.bot()
        bot.store.configure(dict(instanceName='One', appId='cli_one', secret='fake', desiredConnected=True))
        bot.stop()
        bot.start(SimpleNamespace(id='one'))
        deadline = time.monotonic() + 2
        while bot.status()['connectionState'] != 'connected' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual([call[0] for call in bot._transport.calls], ['connect'])

    def test_delayed_resume_does_not_revive_manual_disconnect(self):
        bot = self.bot()
        bot.store.configure(dict(instanceName='One', appId='cli_one', secret='fake', desiredConnected=True))
        bot.stop()
        with bot._network_lock:
            bot.start(SimpleNamespace(id='one'))
            time.sleep(.03)
            with patch.object(bot, '_human'):
                bot.disconnect(ctx=None)
        time.sleep(.05)
        self.assertIsNone(bot._transport)
        self.assertEqual(bot.status()['connectionState'], 'disconnected')

    def test_transport_timeout_has_uncertain_result_and_never_retries(self):
        script = "import sys,time; sys.stdin.readline(); time.sleep(30)"
        transport = WorkerTransport(lambda *_: None, [sys.executable, '-u', '-c', script])
        try:
            with self.assertRaises(PlatformError) as error:
                transport.request('send', {'text': 'hello'}, timeout=.05)
            self.assertEqual(error.exception.code, 'feishu_timeout')
            self.assertIn('结果不确定', error.exception.message)
            self.assertIsNone(transport.process)
        finally:
            transport.close()

    def test_malformed_reader_is_reaped_and_old_eof_cannot_clear_new_generation(self):
        script = "import sys,time; sys.stdin.readline(); print('malformed',flush=True); time.sleep(30)"
        transport = WorkerTransport(lambda *_: None, [sys.executable, '-u', '-c', script])
        with self.assertRaises(PlatformError):
            transport.request('disconnect', timeout=4)
        self.assertIsNone(transport.process)
        old, new = MagicMock(), MagicMock()
        old.poll.return_value = 0
        release = threading.Event()
        def lines():
            release.wait(2)
            return
            yield
        old.stdout.__iter__.side_effect = lines
        pending = Future()
        transport.process = new
        transport._pending['new'] = (new, pending)
        reader = threading.Thread(target=transport._read, args=(old,))
        reader.start()
        release.set()
        reader.join(2)
        self.assertIs(transport.process, new)
        self.assertFalse(pending.done())
        self.assertIn('new', transport._pending)
        transport.process = None


class RealSDKTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        from lark_channel.ws.client import loop
        if not loop.is_running() and not loop.is_closed():
            loop.close()

    def test_official_models_and_send_coercion_without_network(self):
        from lark_channel import FeishuChannel
        from lark_channel.channel.types import InboundMessage, Conversation, Identity, CardActionEvent, CardActionPayload, EventOperator
        captured = []
        session = SDKSession(lambda event, payload: captured.append((event, payload)))
        async def scenario():
            with patch.object(FeishuChannel, 'start_background', new=AsyncMock()), patch.object(FeishuChannel, 'disconnect', new=AsyncMock()):
                await session.handle('connect', {'appId': 'cli_offline', 'secret': 'dummy'})
                channel = session.channel
                second = SDKSession(lambda *_: None)
                await second.handle('connect', {'appId': 'cli_second', 'secret': 'dummy-second'})
                self.assertIsNot(channel, second.channel)
                self.assertIsNot(channel._config, second.channel._config)
                self.assertEqual(channel._config.app_id, 'cli_offline')
                self.assertEqual(second.channel._config.app_id, 'cli_second')
                await second.close()
                channel._sender._driver.create_message = AsyncMock(return_value={'code': 0, 'data': {'message_id': 'om_created'}})
                channel._sender._driver.reply_message = AsyncMock(return_value={'code': 0, 'data': {'message_id': 'om_reply'}})
                result = await session.handle('send', {'targetId': 'oc_test', 'receiveIdType': 'chat_id', 'message': {'text': 'hello'}, 'requestId': 'request-one'})
                self.assertEqual(result['messageId'], 'om_created')
                call = channel._sender._driver.create_message.call_args.kwargs
                self.assertEqual(call['receive_id'], 'oc_test')
                self.assertEqual(json.loads(call['content']), {'text': 'hello'})
                self.assertEqual(call['uuid'], 'request-one')
                await session.handle('send', {'targetId': 'oc_test', 'receiveIdType': 'chat_id', 'message': {'text': 'reply'}, 'replyMessageId': 'om_source'})
                self.assertEqual(channel._sender._driver.reply_message.call_args.kwargs['message_id'], 'om_source')
                card = {'elements': [{'tag': 'markdown', 'content': 'Offline card'}]}
                await session.handle('send_card', {'chatId': 'oc_test', 'card': card, 'requestId': 'card-request'})
                card_call = channel._sender._driver.create_message.call_args.kwargs
                self.assertEqual(card_call['msg_type'], 'interactive')
                self.assertEqual(json.loads(card_call['content']), card)
                self.assertEqual(card_call['uuid'], 'card-request')
                channel._driver.patch_message = AsyncMock(return_value={'code': 0, 'data': {}})
                updated = await session.handle('update_card', {'messageId': 'om_created', 'card': card})
                self.assertTrue(updated['success'])
                self.assertEqual(channel._driver.patch_message.call_args.kwargs,
                                 {'message_id': 'om_created', 'content': json.dumps(card, ensure_ascii=False)})
                message = InboundMessage(id='om_in', create_time=123, conversation=Conversation('oc_test', 'group', 'thread'),
                    sender=Identity('ou_sender', display_name='Sender'), content_text='hello', raw_content_type='text')
                await channel._invoke('message', message)
                action = CardActionEvent(message_id='om_card', chat_id='oc_test', operator=EventOperator(open_id='ou_sender'),
                    action=CardActionPayload(value={'x': 1}, input_value='typed', form_value={'field': 'value'}, checked=True))
                await channel._invoke('cardAction', action)
                self.assertEqual(captured[0][1]['threadId'], 'thread')
                self.assertEqual(captured[1][1]['action']['form_value'], {'field': 'value'})
                self.assertEqual(captured[1][1]['action']['input_value'], 'typed')
                await session.close()
        asyncio.run(scenario())

    def test_safe_errors_do_not_leak_http_or_credentials(self):
        error = RuntimeError('secret=do-not-leak HTTP body')
        error.code = 'permission_denied'
        result = safe_error(error)
        self.assertNotIn('do-not-leak', json.dumps(result))
        self.assertIn('permission_denied', result['code'])

    def test_two_real_sdk_workers_pid_isolation_and_eof_exit(self):
        one, two = WorkerTransport(lambda *_: None), WorkerTransport(lambda *_: None)
        try:
            self.assertEqual(one.request('disconnect')['connectionState'], 'disconnected')
            self.assertEqual(two.request('disconnect')['connectionState'], 'disconnected')
            self.assertNotEqual(one.process.pid, two.process.pid)
            process = one.process
            one.close()
            self.assertEqual(process.returncode, 0)
            self.assertEqual(two.request('disconnect')['connectionState'], 'disconnected')
            two.process.kill()
            two.process.wait(timeout=2)
            self.assertEqual(two.request('disconnect')['connectionState'], 'disconnected')
        finally:
            one.close()
            two.close()
