"""Background package lifecycle, explicit application grants and late-call retirement."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

SERVICE = '''
import threading
class Service:
    def __init__(self, context):
        self.context = context
        self.thread = None
        self.result = None
    def start(self):
        self.context.publish({'started': True})
    def handle(self, command, params):
        if command == 'round':
            def work():
                try:
                    value = self.context.call('model', {})
                    self.context.call('send', value)
                    self.result = 'sent'
                except Exception as error:
                    self.result = str(error)
            self.thread = threading.Thread(target=work)
            self.thread.start()
            return {'started': True}
        return self.context.call('send', params)
    def stop(self):
        if self.thread:
            self.thread.join()
def create(context):
    return Service(context)
'''


class ApplicationBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qt = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        from polaris_platform.bootstrap import build, default_config
        from polaris_platform.component import Component
        from polaris_platform.desktop.application_host import ApplicationHost
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = build(default_config(), state_dir=self.root / 'runtime')
        self.entered, self.release = threading.Event(), threading.Event()
        self.sent = []
        provider = Component()
        def model(params, context):
            self.entered.set()
            self.release.wait()
            return {'text': 'model answer'}
        provider.operation('model', access='write', applicationBinding='instance')(model)
        provider.operation('send', access='write', applicationBinding='instance')(
            lambda params, context: self.sent.append((params, context.origin)) or {'sent': True})
        self.runtime.install(dict(id='provider', name='Provider', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), lambda: provider)
        self.runtime.start_component('provider')
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.root)
        self.pending = []
        self.control = patch('polaris_platform.desktop.application_backend_host.ManagementControlPort.request_application',
                             side_effect=lambda definition, flow, callback, validate: self.pending.append((definition, flow, callback, validate)) or 'approval')
        self.control.start()
        self.addCleanup(self.control.stop)

    def tearDown(self):
        self.release.set()
        self.host.close()
        self.wait(lambda: all(not runner.stopping for runner in self.host._backends.values()))
        for row in reversed(self.runtime.snapshot()):
            if row['state'] == 'running':
                self.runtime.stop_component(row['id'], persist=False)
        self.temp.cleanup()

    def wait(self, predicate):
        from PySide6.QtTest import QTest
        for _ in range(600):
            self.qt.processEvents()
            if predicate():
                return
            QTest.qWait(5)
        self.assertTrue(predicate())

    def install(self, name='test', service=SERVICE, helper=None, callbacks=None):
        directory = self.root / name
        directory.mkdir()
        (directory / 'Main.qml').write_text('import QtQuick\nItem {}')
        (directory / 'backend.py').write_text(service)
        if helper is not None:
            (directory / 'helper.py').write_text(helper)
        (directory / 'polaris-application.json').write_text(json.dumps(dict(id='demo.' + name, name=name, version='1',
            entry=dict(adapter='qt-quick', file='Main.qml', backend='backend.py'),
            requires={alias: dict(componentType='provider', operation=alias, major=1, access='write') for alias in ('model', 'send')},
            callbacks=callbacks or {})))
        self.host.installDirectory(str(directory))
        self.assertFalse(self.host.error, self.host.error)
        identity = self.host._selected
        stable = self.runtime.status('provider')['instanceId']
        self.host.bindInstance('model', stable, 'model')
        self.host.bindInstance('send', stable, 'send')
        self.assertFalse(self.host.error, self.host.error)
        return identity, stable

    def start(self, identity, stable):
        self.host.start_backend(identity)
        definition, flow, callback, validate = self.pending[-1]
        self.assertEqual({step['alias'] for step in definition['flows'][flow]}, {'model', 'send'})
        self.assertTrue(validate())
        self.assertNotIn(identity, self.host._backends)
        for op in ('model', 'send'):
            self.runtime.grant(identity, stable, op)
        callback('confirmed')
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        return self.host._backends[identity]

    def test_packaged_callback_requires_authority_and_dispatches_without_a_view(self):
        from polaris_platform.component import Component
        from polaris_platform.protocol import PlatformError
        service = '''
class Service:
    def __init__(self, context): self.context = context
    def start(self): self.context.publish({'started': True})
    def stop(self): pass
    def handle(self, command, params):
        self.context.publish({'started': True, 'command': command, 'payload': params})
        return {'accepted': True}
def create(context): return Service(context)
'''
        callbacks = {'deliver': dict(contract='test.callback.deliver@1', label='Deliver result',
                                    parameters=dict(type='object', properties={'result': {'type': 'object'}}))}
        identity, stable = self.install(service=service, callbacks=callbacks)
        runner = self.start(identity, stable)
        self.runtime.install(dict(id='callback-source', name='Source', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), Component)
        self.runtime.start_component('callback-source')
        client = self.runtime.client('callback-source')
        payload = {'result': {'reply': 'output'}}
        with self.assertRaises(PlatformError) as denied:
            client.call(identity, 'deliver', payload, self.runtime.user_context('callback-source'))
        self.assertIn(denied.exception.code, ('permission_required', 'permission_denied'))
        self.runtime.grant('callback-source', identity, 'deliver')
        self.host.set_presentation_active(False)
        self.assertEqual(client.call(identity, 'deliver', payload, self.runtime.user_context('callback-source')), {'accepted': True})
        self.assertEqual(runner.state['payload'], payload)
        metadata = self.runtime.status(identity)['description']['operations']['deliver']
        self.assertEqual(metadata['provides'], 'test.callback.deliver@1')
        self.assertEqual(metadata['parameters'], callbacks['deliver']['parameters'])
        self.host.stop_backend(identity)
        with self.assertRaises(PlatformError) as stopped:
            self.host._backend_callback(identity, 'deliver', payload)
        self.assertEqual(stopped.exception.code, 'completion_not_ready')

    def test_missing_bindings_warn_and_call_failure_does_not_stop_backend(self):
        from polaris_platform.protocol import PlatformError
        identity, stable = self.install()
        app = self.host.store.load(identity)
        app.bindings.clear()
        self.host.store.save(app)
        self.host.start_backend(identity)
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        runner = self.host._backends[identity]
        self.assertEqual(len(self.host._backend_warnings[identity]), 2)
        with self.assertRaises(PlatformError):
            runner.call('send', {})
        self.assertTrue(runner.running)
        self.assertEqual(self.pending, [])

    def test_stopped_provider_is_capability_warning_not_missing_component(self):
        identity, stable = self.install()
        self.runtime.stop_component('provider', persist=False)
        self.host.start_backend(identity)
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        self.assertEqual(len(self.host._backend_warnings[identity]), 2)
        self.assertTrue(self.host._backends[identity].running)

    def test_dependency_missing_at_start_and_removed_during_runtime_is_fatal(self):
        from polaris_platform.protocol import PlatformError
        from polaris_platform.application_package import _tree_digest
        identity, stable = self.install()
        app = self.host.store.load(identity)
        root = self.host.packages.directory / app.package['snapshot']
        manifest = root / 'polaris-application.json'
        value = json.loads(manifest.read_text())
        value['dependencies'] = ['required.provider']
        manifest.write_text(json.dumps(value))
        app.package['digest'] = _tree_digest(root)
        self.host.store.save(app)
        with self.assertRaises(PlatformError) as failure:
            self.host.start_backend(identity)
        self.assertEqual(failure.exception.code, 'application_dependency_missing')
        self.assertNotIn(identity, self.host._backends)
        from polaris_platform.component import Component
        self.runtime.install(dict(id='required.provider', name='Required', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), Component)
        runner = self.start(identity, stable)
        self.runtime.uninstall_component('required.provider')
        self.wait(lambda: not runner.running)
        self.assertIn('required.provider', self.host._backend_errors[identity])
        self.assertFalse(self.host._background_enabled(identity))

    def test_explicit_approval_view_hide_and_switch_preserve_enabled_backend(self):
        identity, stable = self.install()
        runner = self.start(identity, stable)
        self.host.set_presentation_active(False)
        self.host.select('')
        self.assertTrue(runner.running)
        runner.call('send', {'text': 'from app'})
        self.assertEqual(self.sent, [({'text': 'from app'}, identity)])
        bindings = runner.context.bindings
        bindings['send']['target'] = 'different'
        self.assertEqual(runner.context.bindings['send']['target'], stable)
        from polaris_platform.protocol import PlatformError
        with self.assertRaises(PlatformError):
            runner.context.call('not-declared', {})

    def test_stop_is_nonblocking_and_late_model_result_cannot_send(self):
        identity, stable = self.install()
        runner = self.start(identity, stable)
        runner.call('round', {})
        self.assertTrue(self.entered.wait(2))
        self.host.stop_backend(identity)
        # The model remains blocked, but GUI-side stop already returned.
        self.assertTrue(runner.stopping)
        self.assertTrue(runner.context.stopped.is_set())
        from polaris_platform.protocol import PlatformError
        with self.assertRaises(PlatformError):
            self.host.start_backend(identity)
        self.release.set()
        self.wait(lambda: not runner.stopping)
        self.assertEqual(self.sent, [])
        self.assertNotEqual(runner._service.result, 'sent')
        self.assertFalse(self.host._background_enabled(identity))

    def test_restore_keeps_running_but_never_grants_missing_authority(self):
        from polaris_platform.desktop.application_host import ApplicationHost
        identity, stable = self.install()
        runner = self.start(identity, stable)
        self.host.close()
        self.wait(lambda: not runner.stopping)
        self.assertTrue(self.host._background_enabled(identity))
        self.runtime.revoke(identity, stable, 'send')
        before = self.runtime.authorization.scope(identity)
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.root)
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        self.assertEqual(self.runtime.authorization.scope(identity), before)
        self.assertTrue(self.host._backend_warnings[identity])
        from polaris_platform.protocol import PlatformError
        with self.assertRaises(PlatformError):
            self.host._backends[identity].call('send', {'text': 'not authorized'})
        self.assertTrue(self.host._backends[identity].running)
        self.assertTrue(self.host._background_enabled(identity))

    def test_restore_waits_for_desktop_providers_to_start(self):
        from polaris_platform.desktop.application_host import ApplicationHost
        identity, stable = self.install()
        runner = self.start(identity, stable)
        self.host.close()
        self.wait(lambda: not runner.stopping)
        self.runtime.stop_component('provider', persist=False)
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.root)
        self.assertNotIn(identity, self.host._backends)
        self.assertNotIn(identity, self.host._backend_errors)
        # Match desktop.run: configure Canvas, start later providers, then
        # enter the Qt event loop. Recovery must use the saved grants only.
        self.runtime.start_component('provider')
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        self.assertNotIn(identity, self.host._backend_errors)
        self.assertEqual(len(self.pending), 1)

    def test_host_exit_retires_late_calls_and_restores_only_saved_grants(self):
        from polaris_platform.desktop.application_host import ApplicationHost
        from polaris_platform.protocol import PlatformError
        identity, stable = self.install()
        old = self.start(identity, stable)
        old.call('round', {})
        self.assertTrue(self.entered.wait(2))
        self.host.close()
        self.assertTrue(old.context.stopped.is_set())
        self.assertTrue(self.host._background_enabled(identity))
        self.release.set()
        self.wait(lambda: not old.stopping)
        self.assertEqual(self.sent, [])
        with self.assertRaises(PlatformError):
            old.context.call('send', {'text': 'old context'})
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.root)
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].state.get('started'))
        restored = self.host._backends[identity]
        restored.call('send', {'text': 'restored context'})
        self.assertEqual(self.sent, [({'text': 'restored context'}, identity)])
        self.assertEqual(len(self.pending), 1, 'restore must not request new authorization')

    def test_revoke_and_remove_stop_service_and_clear_running_intent(self):
        identity, stable = self.install()
        runner = self.start(identity, stable)
        self.host.revoke()
        self.assertTrue(runner.context.stopped.is_set())
        self.assertFalse(self.host._background_enabled(identity))
        self.wait(lambda: not runner.stopping)
        self.host.remove()
        self.assertFalse(self.host._selected)
        self.assertFalse(self.host.store.directory.joinpath(identity + '.json').exists())

    def test_repeated_start_during_approval_keeps_one_request(self):
        identity, stable = self.install()
        self.host.start_backend(identity)
        self.host.start_backend(identity)
        self.assertEqual(len(self.pending), 1)
        self.assertNotIn(identity, self.host._backends)

    def test_background_approval_holds_canvas_until_confirmation_or_cancel(self):
        identity, stable = self.install()
        holds = {}
        self.host._hold = lambda reason, active: holds.update({reason: active})
        self.host.start_backend(identity)
        self.assertTrue(holds['application'])
        # Canvas only ends presentation after its application hold releases.
        if not holds['application']:
            self.host.set_presentation_active(False)
        self.assertIn(identity, self.host._approval_tokens)
        definition, flow, callback, validate = self.pending[-1]
        self.assertTrue(validate())
        for op in ('model', 'send'):
            self.runtime.grant(identity, stable, op)
        callback('confirmed')
        self.assertFalse(holds['application'])
        self.wait(lambda: self.host._backends[identity].state.get('started'))
        self.host.set_presentation_active(False)
        self.assertTrue(self.host._backends[identity].running)

    def test_background_approval_hold_releases_on_stop_and_request_error(self):
        identity, stable = self.install()
        holds = {}
        self.host._hold = lambda reason, active: holds.update({reason: active})
        self.host.start_backend(identity)
        with patch('polaris_platform.desktop.application_backend_host.ManagementControlPort.cancel_approval'):
            self.host.stop_backend(identity)
        self.assertFalse(holds['application'])
        with patch('polaris_platform.desktop.application_backend_host.ManagementControlPort.request_application', side_effect=RuntimeError('request failed')):
            with self.assertRaisesRegex(RuntimeError, 'request failed'):
                self.host.start_backend(identity)
        self.assertFalse(holds['application'])

    def test_stop_then_start_reuses_existing_grants_without_approval(self):
        identity, stable = self.install()
        old = self.start(identity, stable)
        self.host.stop_backend(identity)
        self.wait(lambda: not old.stopping)
        self.host.start_backend(identity)
        self.wait(lambda: self.host._backends[identity] is not old and self.host._backends[identity].state.get('started'))
        self.assertEqual(len(self.pending), 1)
        self.host._backends[identity].call('send', {'text': 'resumed'})
        self.assertEqual(self.sent, [({'text': 'resumed'}, identity)])

    def test_import_cannot_share_another_app_snapshot(self):
        from uuid import uuid4
        identity, stable = self.install()
        original = self.host.store.load(identity)
        value = original.as_dict()
        value['applicationId'] = uuid4().hex
        self.host.importJson(json.dumps(value))
        self.assertNotIn(value['applicationId'], {r['applicationId'] for r in self.host.store.list()})
        self.host.packages.load_verified(original)

    def test_update_preserves_identity_data_bindings_authority_and_intent(self):
        identity, stable = self.install()
        old = self.start(identity, stable)
        previous = self.host.store.load(identity)
        data = self.host.application_data_directory(identity)
        (data / 'queue.json').write_text('queued')
        scope = self.runtime.authorization.scope(identity)
        source = self.root / 'test'
        manifest = json.loads((source / 'polaris-application.json').read_text())
        manifest['version'] = '2'
        (source / 'polaris-application.json').write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        self.wait(lambda: identity not in self.host._package_updates)
        current = self.host.store.load(identity)
        self.assertEqual(current.id, identity)
        self.assertEqual(current.bindings, previous.bindings)
        self.assertNotEqual(current.package['snapshot'], previous.package['snapshot'])
        self.assertEqual((data / 'queue.json').read_text(), 'queued')
        self.assertEqual(self.runtime.authorization.scope(identity), scope)
        self.assertTrue(self.host._background_enabled(identity))
        self.wait(lambda: self.host._backends[identity] is not old and self.host._backends[identity].state.get('started'))
        self.assertFalse((self.host.packages.directory / previous.package['snapshot']).exists())
        self.assertEqual(self.host.packages.load_verified(current)['manifest']['version'], '2')

    def test_update_added_requirement_warns_and_never_grants(self):
        identity, stable = self.install()
        self.start(identity, stable)
        before = self.runtime.authorization.scope(identity)
        source = self.root / 'test'
        manifest = json.loads((source / 'polaris-application.json').read_text())
        manifest['requires']['extra'] = manifest['requires']['send'].copy()
        (source / 'polaris-application.json').write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        self.wait(lambda: identity not in self.host._package_updates)
        self.assertNotIn('extra', self.host.store.load(identity).bindings)
        self.assertNotIn(identity, self.host._backend_errors)
        self.wait(lambda: self.host._backends[identity].state.get('started'))
        self.assertTrue(any('extra' in item for item in self.host._backend_warnings[identity]))
        self.assertEqual(self.runtime.authorization.scope(identity), before)
        self.assertTrue(self.host._background_enabled(identity))
        self.assertEqual(len(self.pending), 1)

    def test_update_save_failure_retains_old_verified_package_and_references(self):
        identity, stable = self.install()
        previous = self.host.store.load(identity)
        snapshots = set(self.host.packages.directory.iterdir())
        with patch.object(self.host.store, 'save', side_effect=OSError('disk failure')):
            self.host.updateDirectory(str(self.root / 'test'))
        self.assertIn('disk failure', self.host._notice)
        self.assertEqual(self.host.store.load(identity).as_dict(), previous.as_dict())
        self.host.packages.load_verified(previous)
        self.assertEqual(set(self.host.packages.directory.iterdir()), snapshots)
        self.assertEqual(self.runtime._application_bindings[identity], {stable})

    def test_update_drops_changed_requirement_and_rejects_other_package(self):
        identity, stable = self.install()
        previous = self.host.store.load(identity)
        source = self.root / 'test'
        path = source / 'polaris-application.json'
        manifest = json.loads(path.read_text())
        manifest['id'] = 'different.application'
        path.write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        self.assertEqual(self.host.store.load(identity).as_dict(), previous.as_dict())
        self.host.packages.load_verified(previous)
        manifest['id'] = 'demo.test'
        manifest['requires']['send']['major'] = 2
        path.write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        self.assertEqual(set(self.host.store.load(identity).bindings), {'model'})

    def test_update_waits_for_old_service_without_allowing_late_send(self):
        identity, stable = self.install()
        old = self.start(identity, stable)
        old.call('round', {})
        self.assertTrue(self.entered.wait(2))
        previous = self.host.store.load(identity)
        self.host.updateDirectory(str(self.root / 'test'))
        self.assertIn(identity, self.host._package_updates)
        self.assertEqual(self.host.store.load(identity).package, previous.package)
        self.assertTrue(old.context.stopped.is_set())
        self.release.set()
        self.wait(lambda: identity not in self.host._package_updates)
        self.assertNotEqual(self.host.store.load(identity).package, previous.package)
        self.assertEqual(self.sent, [])

    def test_update_stop_failure_keeps_old_definition_and_package(self):
        identity, stable = self.install(service=SERVICE.replace("    def stop(self):\n", "    def stop(self):\n        raise RuntimeError('stop failed')\n"))
        self.start(identity, stable)
        previous = self.host.store.load(identity)
        self.host.updateDirectory(str(self.root / 'test'))
        self.wait(lambda: identity not in self.host._package_updates)
        self.assertIn('stop failed', self.host._notice)
        self.assertEqual(self.host.store.load(identity).as_dict(), previous.as_dict())
        self.host.packages.load_verified(previous)

    def test_foreground_only_package_can_update_without_backend(self):
        identity, stable = self.install()
        source = self.root / 'test'
        path = source / 'polaris-application.json'
        manifest = json.loads(path.read_text())
        manifest['entry'].pop('backend')
        path.write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        previous = self.host.store.load(identity)
        self.assertIsNone(self.host.packages.load_verified(previous)['backend'])
        manifest['version'] = '3'
        path.write_text(json.dumps(manifest))
        self.host.updateDirectory(str(source))
        current = self.host.store.load(identity)
        self.assertEqual(current.id, identity)
        self.assertIsNone(self.host.packages.load_verified(current)['backend'])
        self.assertEqual(self.host.packages.load_verified(current)['manifest']['version'], '3')
        self.assertFalse(self.host._background_enabled(identity))

    def test_startup_failure_stops_created_service_and_unloads_module(self):
        broken = SERVICE.replace("        self.context.publish({'started': True})", "        raise RuntimeError('service startup failed')").replace("    def stop(self):\n        if self.thread:", "    def stop(self):\n        self.context.data_directory.joinpath('stopped').write_text('yes')\n        if self.thread:")
        identity, stable = self.install(service=broken)
        self.host.start_backend(identity)
        for op in ('model', 'send'):
            self.runtime.grant(identity, stable, op)
        self.pending[-1][2]('confirmed')
        self.wait(lambda: identity in self.host._backends and self.host._backends[identity].error)
        runner = self.host._backends[identity]
        self.wait(runner.stopped.is_set)
        self.assertEqual(runner.error, 'service startup failed')
        self.assertFalse(runner.running)
        self.assertTrue(runner.context.stopped.is_set())
        self.assertTrue(runner.context.data_directory.joinpath('stopped').exists())
        import sys
        self.assertNotIn(runner._module_name, sys.modules)

    def test_relative_helper_import_does_not_change_verified_snapshot(self):
        source = 'from .helper import VALUE\n' + SERVICE.replace("{'started': True}", "{'started': True, 'value': VALUE}")
        identity, stable = self.install(service=source, helper='VALUE = 42')
        runner = self.start(identity, stable)
        self.assertEqual(runner.state['value'], 42)
        verified = self.host.packages.load_verified(self.host.store.load(identity))
        self.assertFalse(list(verified['backend'].parent.rglob('*.pyc')))

    def test_backend_modules_are_unique_and_python_snapshot_is_verified(self):
        one, stable = self.install('one')
        first = self.start(one, stable)
        two, stable = self.install('two')
        second = self.start(two, stable)
        self.assertNotEqual(first._module_name, second._module_name)
        definition = self.host.store.load(two)
        verified = self.host.packages.load_verified(definition)
        verified['backend'].write_text(SERVICE + '\n# changed')
        from polaris_platform.protocol import PlatformError
        with self.assertRaises(PlatformError) as error:
            self.host.packages.load_verified(definition)
        self.assertEqual(error.exception.code, 'application_package_changed')
