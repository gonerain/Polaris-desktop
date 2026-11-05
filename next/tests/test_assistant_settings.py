"""First-use model setup, local credential persistence and native UI authority."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from components import manifest
from components.assistant import Assistant, settings
from components.assistant.model import ModelError, configured_model
from components.assistant.tools import operations
from polaris_platform.bootstrap import build, default_config
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Setup must not call a service'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_first_use_save_all_existing_services_and_restart_without_returning_keys(self):
        self.assertFalse(settings.snapshot(self.directory)['ready'])
        for provider in ('deepseek', 'bigmodel', 'zai'):
            with self.subTest(provider=provider):
                key = 'fixture-' + provider + '-private'
                settings.save(self.directory, provider, key)
                state = settings.snapshot(self.directory)
                self.assertTrue(state['ready'])
                self.assertEqual(state['provider'], provider)
                self.assertEqual(configured_model(self.directory)._key, key)
                self.assertNotIn(key, json.dumps(state))
                self.assertEqual(stat.S_IMODE((self.directory / (provider + '-api-key')).stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE((self.directory / 'model.json').stat().st_mode), 0o600)

    def test_blank_key_preserves_secret_and_reasoning_effort(self):
        settings.save(self.directory, 'deepseek', 'fixture-original-secret')
        path = self.directory / 'model.json'
        path.write_text(json.dumps(dict(version=1, provider='deepseek', reasoning_effort='high')))
        settings.save(self.directory, 'deepseek', '')
        self.assertEqual(configured_model(self.directory)._key, 'fixture-original-secret')
        self.assertEqual(configured_model(self.directory).reasoning_effort, 'high')
        settings.save(self.directory, 'bigmodel', 'fixture-other-secret')
        self.assertEqual(configured_model(self.directory).reasoning_effort, 'high')

    def test_environment_overrides_are_reported_without_echoing_secrets(self):
        settings.save(self.directory, 'bigmodel', 'fixture-local-secret')
        with patch.dict(os.environ, {'POLARIS_AGENT_MODEL_PROVIDER': 'zai', 'ZAI_API_KEY': 'fixture-env-secret'}):
            state = settings.snapshot(self.directory)
            self.assertEqual((state['savedProvider'], state['provider']), ('bigmodel', 'zai'))
            self.assertTrue(state['providerOverride'])
            self.assertTrue(next(p for p in state['providers'] if p['id'] == 'zai')['keyOverride'])
            self.assertNotIn('fixture-', json.dumps(state))
            settings.save(self.directory, 'zai', '')
            self.assertFalse((self.directory / 'zai-api-key').exists())

    def test_invalid_reasoning_remains_visible_and_corrupt_settings_can_be_repaired(self):
        settings.save(self.directory, 'deepseek', 'fixture-local-secret')
        path = self.directory / 'model.json'
        path.write_text('{"version":1,"provider":"deepseek","reasoning_effort":"invalid"}')
        settings.save(self.directory, 'bigmodel', 'fixture-other-secret')
        state = settings.snapshot(self.directory)
        self.assertFalse(state['ready'])
        self.assertIn('reasoning_effort', state['detail'])
        path.write_text('{"version":1,"provider":{"invalid":true}}')
        self.assertFalse(settings.snapshot(self.directory)['ready'])
        path.write_text('broken')
        settings.save(self.directory, 'deepseek', '')
        self.assertTrue(settings.snapshot(self.directory)['ready'])

    def test_missing_or_invalid_key_does_not_create_settings(self):
        for key in ('', 'short', 'contains a space', 'secret\ninside'):
            with self.subTest(key_length=len(key)), self.assertRaises(ModelError):
                settings.save(self.directory, 'deepseek', key)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_key_write_failure_and_settings_commit_failure_are_safe_and_preserve_previous_files(self):
        settings.save(self.directory, 'deepseek', 'fixture-original-secret')
        key_path, model_path = self.directory / 'deepseek-api-key', self.directory / 'model.json'
        old_key, old_settings = key_path.read_bytes(), model_path.read_bytes()
        real_stage = settings._stage
        def fail_key(path, contents):
            if path == key_path:
                raise OSError('fixture-new-secret')
            return real_stage(path, contents)
        with patch.object(settings, '_stage', fail_key), self.assertRaises(ModelError) as caught:
            settings.save(self.directory, 'deepseek', 'fixture-new-secret')
        self.assertNotIn('fixture-', str(caught.exception))
        self.assertEqual((key_path.read_bytes(), model_path.read_bytes()), (old_key, old_settings))
        real_replace = os.replace
        def fail_settings(source, target):
            if Path(target) == model_path:
                raise OSError('fixture-new-secret')
            return real_replace(source, target)
        with patch.object(settings.os, 'replace', fail_settings), self.assertRaises(ModelError):
            settings.save(self.directory, 'deepseek', 'fixture-new-secret')
        self.assertEqual((key_path.read_bytes(), model_path.read_bytes()), (old_key, old_settings))
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['deepseek-api-key', 'model.json'])

    def test_ordinary_and_background_calls_are_denied_even_when_granted(self):
        runtime = build(default_config())
        agent = Assistant(data_dir=self.directory)
        runtime.install(manifest('assistant'), lambda: agent)
        runtime.start_component('assistant')
        runtime.install(dict(id='mcp', name='mcp', version='1', platformApi=1, entry=dict(mode='inprocess')), Component)
        runtime.start_component('mcp')
        try:
            for caller in ('assistant', 'mcp'):
                runtime.grant(caller, 'assistant', 'configure_model')
                runtime.grant(caller, 'assistant', 'configure_model', background=True)
                for context in (runtime.user_context(caller), runtime.background_context(caller)):
                    with self.subTest(caller=caller, source=context.source), self.assertRaises(PlatformError) as caught:
                        runtime.client(caller).call('assistant', 'configure_model',
                            dict(provider='deepseek', api_key='fixture-secret'), context=context)
                    self.assertEqual(caught.exception.code, 'permission_denied')
            description = runtime.status('assistant')['description']
            self.assertNotIn('configure_model', operations(dict(description=description)))
            self.assertEqual(list(self.directory.iterdir()), [])
        finally:
            for row in reversed(runtime.snapshot()):
                if row['state'] == 'running':
                    runtime.stop_component(row['id'], persist=False)

    def test_failed_commit_and_failed_rollback_retain_private_recovery_copy(self):
        settings.save(self.directory, 'deepseek', 'fixture-original-secret')
        key_path = self.directory / 'deepseek-api-key'
        real_replace = os.replace
        key_writes = []
        def fail_commit_and_rollback(source, target):
            if Path(target) == self.directory / 'model.json':
                raise OSError('cannot commit')
            if Path(target) == key_path:
                key_writes.append(source)
                if len(key_writes) == 2:
                    raise OSError('cannot restore')
            return real_replace(source, target)
        with patch.object(settings.os, 'replace', fail_commit_and_rollback), self.assertRaises(ModelError) as caught:
            settings.save(self.directory, 'deepseek', 'fixture-new-secret')
        backups = list(self.directory.glob('deepseek-api-key.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text().strip(), 'fixture-original-secret')
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertIn(backups[0].name, str(caught.exception))
        self.assertNotIn('fixture-', str(caught.exception))

    def test_native_first_use_flow_in_default_canvas_card(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--ui'],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                     PATH=os.environ.get('PATH', '/usr/bin:/bin')),
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def run_ui():
    import time
    from PySide6.QtCore import QObject, QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from polaris_platform.desktop import WindowHost, Canvas
    from components.assistant.loop import AgentResult
    app = QGuiApplication([])
    def find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find(child, name)
            if found is not None:
                return found
    def wait(predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        assert predicate(), 'UI did not complete'
    with tempfile.TemporaryDirectory() as directory:
        runtime = build(default_config())
        host, canvas, agent = WindowHost(runtime=runtime), Canvas(runtime=runtime, collapse_delay=600000), Assistant(data_dir=directory)
        for identity, component in [('window', host), ('canvas', canvas), ('assistant', agent), ('user', Component())]:
            runtime.install(manifest('assistant') if identity == 'assistant' else dict(id=identity, name=identity, version='1', platformApi=1, entry=dict(mode='inprocess')), lambda c=component: c)
            runtime.start_component(identity)
        for target in ('window', 'canvas', 'assistant'):
            for operation in runtime.status(target)['description']['operations']:
                runtime.grant('user', target, operation)
        context = runtime.user_context('user')
        def call(target, operation, params=None):
            return runtime.client('user').call(target, operation, params, context=context)
        call('canvas', 'show')
        call('canvas', 'mount', dict(target='assistant', view='main', descriptor=agent.views[0]))
        window = host._views[canvas.handle]
        wait(lambda: bool(agent.presentation and agent.presentation.views))
        _, chat = next(iter(agent.presentation.views.values()))
        def item(name):
            result = find(window.contentItem(), name)
            assert result is not None, name
            return result
        def click(name):
            target = item(name)
            point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2))
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(30)
        try:
            assert not agent.configuration_status()['ready']
            assert not item('sendMessage').isEnabled()
            click('modelSettingsButton')
            item('modelProvider').setProperty('currentIndex', 1)
            item('modelApiKey').setProperty('text', 'fixture-ui-secret')
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No paid request')):
                click('saveModelSettings')
            assert agent.configuration_status()['provider'] == 'bigmodel'
            assert agent.configuration_status()['ready']
            assert item('modelApiKey').property('text') == ''
            assert item('modelProvider').property('currentIndex') == 1
            assert '已保存' in item('modelSettingsNotice').property('text')
            view_item, _ = next(iter(agent.presentation.views.values()))
            dialog = view_item.findChild(QObject, 'modelSettingsDialog')
            assert dialog is not None
            assert dialog.property('height') < window.height()
            # Save/close remain visible after shrinking; long content scrolls.
            window.resize(380, 280)
            QTest.qWait(50)
            save_button = item('saveModelSettings')
            point = save_button.mapToScene(QPointF(1, 1))
            assert 0 <= point.y() < window.height() - save_button.height()
            screenshot = os.environ.get('POLARIS_SETTINGS_SCREENSHOT')
            if screenshot:
                path = Path(screenshot)
                window.grabWindow().save(str(path.with_name(path.stem + '-small' + path.suffix)))
            window.resize(880, 620)
            QTest.qWait(50)
            if screenshot:
                window.grabWindow().save(screenshot)
            dialog.close()
            QTest.qWait(20)
            class Echo:
                def run(self, text, history, tools, cancel):
                    return AgentResult('设置完成，可以继续对话。', [{'role':'user','content':text}, {'role':'assistant','content':'设置完成，可以继续对话。'}])
            agent.engine = Echo()
            item('messageDraft').setProperty('text', '你好，开始使用 Polaris Agent。')
            click('sendMessage')
            wait(lambda: item('conversationList').property('count') == 2)
            if screenshot:
                path = Path(screenshot)
                window.grabWindow().save(str(path.with_name(path.stem + '-chat' + path.suffix)))
            saves = []
            chat.settingsSaved.connect(lambda success, message: saves.append((success, message)))
            saved_engine = agent.engine
            with patch.object(settings, '_stage', side_effect=OSError('fixture-secret')):
                chat.saveModel('deepseek', 'fixture-failed-secret')
            assert saves[-1][0] is False and '保存失败' in saves[-1][1]
            assert agent.engine is saved_engine and agent.configuration_status()['provider'] == 'bigmodel'
            dialog.open()
            QTest.qWait(20)
            # A different view's active turn blocks saves and retains its engine.
            class Blocking:
                def __init__(self):
                    self.entered, self.done = threading.Event(), threading.Event()
                def run(self, text, history, tools, cancel):
                    self.entered.set()
                    self.done.wait(3)
                    raise ModelError('fixture-old-secret')
                def _safe(self, value):
                    return str(value).replace('fixture-old-secret', '[已隐藏密钥]')
            engine = Blocking()
            agent.engine = engine
            answers = []
            chat.answered.connect(lambda text, error: answers.append((text, error)))
            chat.submit('测试')
            wait(engine.entered.is_set)
            chat.saveModel('deepseek', 'fixture-new-secret')
            assert saves[-1][0] is False and '正在回复' in saves[-1][1]
            assert agent.engine is engine and agent.configuration_status()['provider'] == 'bigmodel'
            engine.done.set()
            wait(lambda: bool(answers))
            assert 'fixture-old-secret' not in str(answers)
            chat.saveModel('deepseek', 'fixture-new-secret')
            assert saves[-1][0] is True and agent.engine is None
            assert agent.configuration_status()['provider'] == 'deepseek'
            # Hidden/released native views cannot keep saving.
            window.hide()
            chat.saveModel('bigmodel', 'fixture-hidden-secret')
            assert saves[-1][0] is False
            assert agent.configuration_status()['provider'] == 'deepseek'
        finally:
            for row in reversed(runtime.snapshot()):
                if row['state'] == 'running':
                    runtime.stop_component(row['id'], force=True, persist=False)
            QTest.qWait(40)


if __name__ == '__main__':
    if '--ui' in sys.argv:
        run_ui()
    else:
        unittest.main()
