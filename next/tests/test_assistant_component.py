import sys
import tempfile
import unittest
from pathlib import Path

from components import manifest
from components.assistant import Assistant
from components.assistant.loop import AgentResult
from polaris_platform.bootstrap import build, default_config
from polaris_platform.component import Component


class Echo:
    def run(self, text, history, tools, cancel):
        answer = str(len(history)) + ':' + text
        return AgentResult(answer, [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': answer}])


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.rt = build(default_config())
        self.rt.install(manifest('assistant'), lambda: Assistant(Echo()))
        self.rt.start_component('assistant')
        for name in ('first', 'second'):
            self.rt.install(dict(id=name, name=name, version='1', platformApi=1, entry=dict(mode='inprocess')), Component)
            self.rt.start_component(name)
            self.rt.grant(name, 'assistant', 'reply')
        self.addCleanup(self.stop)

    def stop(self):
        for row in reversed(self.rt.snapshot()):
            if row['state'] == 'running':
                self.rt.stop_component(row['id'], persist=False)

    def call(self, name, **params):
        return self.rt.client(name).call('assistant', 'reply', params, self.rt.user_context(name))

    def test_standalone_conversations_and_last_confirmed_turn(self):
        first = self.call('first', text='one')
        self.assertEqual(first['text'], '0:one')
        self.assertEqual(self.call('second', text='private')['text'], '0:private')
        self.assertEqual(self.call('first', text='unconfirmed', parent=first['turn'])['text'], '2:unconfirmed')
        self.assertEqual(self.call('first', text='retry', parent=first['turn'])['text'], '2:retry')
        self.assertNotIn('polaris_weixin', sys.modules)
        self.assertNotIn('polaris_agent', sys.modules)

    def test_channel_limit_applies_only_to_requested_reply_and_its_history(self):
        result = self.call('first', text='字' * 3000, max_reply_chars=2000)
        self.assertEqual(len(result['text']), 2000)
        self.assertTrue(result['text'].endswith('已截短）'))
        self.assertGreater(len(self.call('second', text='字' * 3000)['text']), 2000)

    def test_chat_tool_switch_uses_only_the_origins_existing_grants(self):
        toy = Component()
        toy.operation('lookup')(lambda p, c: 'OK')
        toy.operation('other')(lambda p, c: 'not granted')
        self.rt.install(dict(id='toy', name='toy', version='1', platformApi=1, entry=dict(mode='inprocess')), lambda: toy)
        self.rt.start_component('toy')
        for target, op in [('toy','lookup'), ('collaboration','discover'), ('collaboration','describe')]:
            self.rt.grant('first', target, op)
        class ToolModel:
            def run(_, text, history, tools, cancel):
                self.assertEqual(tools.allowed, {('toy','lookup')})
                tools.execute('help', {'component':'toy'}, cancel)
                reply = tools.execute('call', {'component':'toy','operation':'lookup'}, cancel)
                return AgentResult(reply, [])
        self.rt.component_instance('assistant').engine = ToolModel()
        self.assertEqual(self.call('first', text='check', use_authorized_tools=True)['text'], 'OK')

    def test_chat_view_sends_via_real_context(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        app = QGuiApplication.instance() or QGuiApplication([])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'Root.qml'
            path.write_text('import QtQuick\nItem {width: 400; height: 300}', encoding='utf-8')
            window = QQuickView()
            window.setSource(QUrl.fromLocalFile(str(path)))
            for op in ('create_view', 'release_view'):
                self.rt.grant('first', 'assistant', op)
            client, ctx = self.rt.client('first'), self.rt.user_context('first')
            view = client.call('assistant', 'create_view', dict(view='main', parent=window.rootObject()), ctx)
            try:
                service = self.rt.component_instance('assistant')
                chat = service.presentation.views[view['handle']][1]
                result = []
                chat.answered.connect(lambda text, error: result.append((text, error)))
                chat.submit('hello')
                for _ in range(200):
                    if result:
                        break
                    QTest.qWait(10)
                self.assertEqual(result, [('0:hello', '')])
            finally:
                client.call('assistant', 'release_view', {'handle':view['handle']}, ctx)
                window.close()
