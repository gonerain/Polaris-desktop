"""Desktop application import, explicit approval and independent execution."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class ApplicationHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qt = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        from polaris_platform.bootstrap import build, default_config
        from polaris_platform.component import Component
        from polaris_platform.application import Application
        from polaris_platform.desktop.application_host import ApplicationHost
        from polaris_platform.desktop.manager import ManagerBridge
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = build(default_config(), state_dir=Path(self.temporary.name) / 'runtime')
        self.calls = []
        component = Component()
        component.operation('echo', applicationBinding='instance')(lambda params, context: self.calls.append(context.origin) or dict(params))
        self.runtime.install(dict(id='provider', name='Echo provider', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), lambda: component)
        self.runtime.start_component('provider')
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.temporary.name)
        self.app = Application('Echo application')
        client = self.runtime.client('provider')
        status = self.runtime.status('provider')
        stable = status['instanceId']
        self.app.bindings = {'echo': dict(target=stable, installationId=stable, instanceId=stable,
                                         operation='echo', semantic=list(client.bind(stable, 'echo').semantic))}
        self.app.flows = {'echo': [{'alias': 'echo', 'input': 'previous'}]}
        self.app.pages = [{'id': 'main', 'title': 'Say hello', 'action': 'echo',
                           'inputs': [{'name': 'message', 'label': 'Message', 'default': 'Hello'}]}]
        self.bridge = ManagerBridge(self.runtime)

    def tearDown(self):
        self.host.close()
        self.bridge.cancel_all()
        self.bridge._closed = True
        for row in reversed(self.runtime.snapshot()):
            if row['state'] == 'running':
                self.runtime.stop_component(row['id'], persist=False)
        self.temporary.cleanup()

    def wait(self, predicate):
        from PySide6.QtTest import QTest
        for _ in range(600):
            self.qt.processEvents()
            if predicate(): return
            QTest.qWait(5)
        self.assertTrue(predicate())

    def import_app(self):
        self.host.importJson(json.dumps(self.app.as_dict()))
        self.assertFalse(self.host.error)

    def test_import_is_validated_durable_and_never_grants(self):
        self.import_app()
        self.assertEqual(len(json.loads(self.host.applicationsJson)), 1)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))
        self.host.importJson(json.dumps(self.app.as_dict()))
        self.assertIn('已存在', self.host.error)
        invalid = self.app.as_dict()
        invalid['pages'][0]['inputs'][0]['label'] = 3
        self.host.importJson(json.dumps(invalid))
        self.assertIn('Inputs require', self.host.error)
        self.assertEqual(len(list((Path(self.temporary.name) / 'applications').glob('*.json'))), 1)

    def test_approval_is_explicit_and_execution_uses_only_app_origin(self):
        self.import_app()
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('echo', '{"message":"hello"}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.assertEqual(self.host.state, 'approval')
            self.assertFalse(self.calls)
            self.assertFalse(self.runtime.authorization.scope(self.app.id))
            plan = self.bridge._pending_plan
            self.assertEqual(plan['permissions'][0]['target'], self.app.bindings['echo']['instanceId'])
            self.bridge.confirmView()
            self.wait(lambda: self.host.state == 'done')
        self.assertEqual(self.calls, [self.app.id])
        self.assertEqual(json.loads(self.host.result), {'message': 'hello'})
        self.assertFalse(self.runtime.authorization.scope(self.app.id, True))
        self.runtime.revoke(self.app.id, 'provider', 'echo')
        self.assertFalse(self.runtime.authorization.scope(self.app.id))

    def test_cancelled_or_stale_approval_cannot_execute(self):
        self.import_app()
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('echo', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.bridge.cancelView()
            self.wait(lambda: self.host.state == 'error')
        self.assertFalse(self.calls)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))

    def test_definition_change_invalidates_pending_approval_without_grant(self):
        self.import_app()
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('echo', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.app.title = 'Changed definition'
            self.host.store.save(self.app)
            self.bridge.confirmView()
            self.wait(lambda: self.host.state == 'error')
        self.assertFalse(self.calls)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))

    def test_revoke_and_remove_clear_authority_and_preserve_or_release_references(self):
        from polaris_platform.protocol import PlatformError
        self.import_app()
        self.runtime.grant(self.app.id, 'provider', 'echo')
        self.runtime.grant(self.app.id, 'provider', 'echo', background=True)
        old_client = self.runtime.application_client(self.app.id)
        old_context = self.runtime.application_context(self.app.id)
        self.host.revoke()
        self.assertFalse(self.host.error)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))
        self.assertFalse(self.runtime.authorization.scope(self.app.id, True))
        with self.assertRaises(PlatformError): old_client.bind('provider', 'echo')
        with self.assertRaises(PlatformError): self.runtime.validate_context(old_context)
        with self.assertRaises(PlatformError) as caught: self.runtime.uninstall_component('provider')
        self.assertEqual(caught.exception.code, 'instance_in_use')
        self.runtime.grant(self.app.id, 'provider', 'echo')
        self.host.remove()
        self.assertFalse(self.host.error)
        self.assertEqual(self.host.store.list(), [])
        with self.assertRaises(PlatformError): self.runtime.application_client(self.app.id)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))
        self.runtime.uninstall_component('provider')

    def test_failed_removal_retains_visible_definition_and_no_authority(self):
        self.import_app()
        self.runtime.grant(self.app.id, 'provider', 'echo')
        with patch.object(self.host.store, 'delete', side_effect=OSError('disk failure')):
            self.host.remove()
        self.assertIn('移除应用失败', self.host.error)
        self.assertEqual(len(self.host.store.list()), 1)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))
        self.runtime.grant(self.app.id, 'provider', 'echo')
        with patch.object(self.runtime, 'unregister_application_principal', side_effect=OSError('records failure')):
            self.host.remove()
        self.assertIn('移除应用失败', self.host.error)
        self.assertEqual(len(self.host.store.list()), 1)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))

    def test_corrupt_definition_during_approval_finishes_and_releases_hold(self):
        self.import_app()
        holds = []
        self.host._hold = lambda reason, active: holds.append(active)
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('echo', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.host.store._path(self.app.id).write_text('{')
            self.bridge.confirmView()
            self.wait(lambda: not self.host.busy)
        self.assertEqual(holds[-1], False)
        self.assertFalse(self.calls)
        self.assertFalse(self.runtime.authorization.scope(self.app.id))

    def test_import_cannot_supply_provider_opt_in(self):
        component = self.runtime.component_instance('provider')
        component._operations['echo'].pop('applicationBinding')
        component.port.advertise()
        self.host.importJson(json.dumps(self.app.as_dict()))
        self.assertIn('稳定实例应用绑定', self.host.error)
        self.assertEqual(self.host.store.list(), [])

    def test_two_instances_share_installation_but_approval_and_data_are_independent(self):
        from polaris_platform.component import Component
        def factory(instance_context):
            component = Component()
            component.operation('echo', applicationBinding='instance')(lambda params, context: {'label': instance_context['config'].get('label', '')})
            return component
        self.runtime.install(dict(id='multi', name='Multi', version='1', platformApi=1,
                                  instances={'mode': 'multiple'}, entry={'mode': 'inprocess'}), factory)
        first = self.runtime.create_instance('multi', config={'label': 'first'})
        second = self.runtime.create_instance('multi', config={'label': 'second'})
        for identity in (first, second): self.runtime.start_instance(identity)
        client = self.runtime.client('provider')
        for alias, identity in [('first', first), ('second', second)]:
            status = self.runtime.status(identity)
            self.app.bindings[alias] = dict(target=identity, installationId=status['installationId'],
                                           instanceId=identity, operation='echo', semantic=list(client.bind(identity, 'echo').semantic))
            self.app.flows[alias] = [{'alias': alias, 'input': 'previous'}]
        self.import_app()
        first_plan = self.bridge._make_application_plan(self.app.as_dict(), 'first')
        second_plan = self.bridge._make_application_plan(self.app.as_dict(), 'second')
        self.assertEqual(self.app.bindings['first']['installationId'], self.app.bindings['second']['installationId'])
        self.assertNotEqual(first_plan['permissions'][0]['key'], second_plan['permissions'][0]['key'])
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('first', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.bridge.confirmView()
            self.wait(lambda: self.host.state == 'done')
            self.assertEqual(json.loads(self.host.result), {'label': 'first'})
            self.host.run('second', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.assertFalse(self.bridge._pending_plan['permissions'][0]['authorized'])
            self.bridge.confirmView()
            self.wait(lambda: self.host.state == 'done')
            self.assertEqual(json.loads(self.host.result), {'label': 'second'})

    def test_failed_import_rolls_back_principal_and_references(self):
        from polaris_platform.protocol import PlatformError
        invalid = self.app.as_dict()
        invalid['bindings']['echo']['target'] = 'missing'
        invalid['bindings']['echo']['instanceId'] = 'missing'
        invalid['bindings']['echo']['semantic'][0] = 'missing'
        self.host.importJson(json.dumps(invalid))
        self.assertTrue(self.host.error)
        self.assertEqual(self.host.store.list(), [])
        with self.assertRaises(PlatformError) as caught:
            self.runtime.application_client(self.app.id)
        self.assertEqual(caught.exception.code, 'unknown_application')

    def test_close_stops_later_flow_steps_and_switch_does_not_show_other_result(self):
        import threading
        from polaris_platform.application import Application
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        component = self.runtime.component_instance('provider')
        later = []
        def blocking(params, context):
            entered.set()
            release.wait(3)
            returned.set()
            return {'private': 'first application'}
        component.operation('block', applicationBinding='instance')(blocking)
        component.operation('later', applicationBinding='instance')(lambda p, ctx: later.append(True) or p)
        client = self.runtime.client('provider')
        stable = self.runtime.status('provider')['instanceId']
        for alias in ('block', 'later'):
            self.app.bindings[alias] = dict(target=stable, instanceId=stable, installationId=stable,
                                           operation=alias, semantic=list(client.bind(stable, alias).semantic))
        self.app.flows['blocking'] = [{'alias': 'block'}, {'alias': 'later', 'input': 'previous'}]
        self.import_app()
        other = Application('Other application')
        self.host.importJson(json.dumps(other.as_dict()))
        self.host.select(self.app.id)
        def request(port, definition, flow, callback, validate=None):
            return self.bridge.request_application(definition, flow, callback, validate)
        with patch('polaris_platform.desktop.management_control.ManagementControlPort.request_application', request):
            self.host.run('blocking', '{}')
            self.wait(lambda: not self.bridge.busy and self.bridge._pending_plan is not None)
            self.bridge.confirmView()
            self.wait(entered.is_set)
            self.host.select(other.id)
            self.assertEqual(self.host.result, '')
            self.assertEqual(self.host.state, 'idle')
            self.assertTrue(self.host.busy)
            self.assertEqual(self.host.busyTitle, self.app.title)
            self.host.close()
            release.set()
            self.wait(returned.is_set)
            from PySide6.QtTest import QTest
            QTest.qWait(60)
        self.assertFalse(later)
        self.assertEqual(self.host.result, '')

    def test_installed_application_blocks_instance_deletion(self):
        from polaris_platform.protocol import PlatformError
        self.import_app()
        def extra(instance_context=None):
            from polaris_platform.component import Component
            c = Component()
            c.operation('echo', applicationBinding='instance')(lambda p, ctx: p)
            return c
        self.runtime.install(dict(id='extra', name='extra', version='1', platformApi=1,
                                  instances={'mode': 'multiple'}, entry={'mode': 'inprocess'}), extra)
        stable = self.runtime.create_instance('extra')
        self.runtime.register_application_bindings(self.app.id, [stable])
        with self.assertRaises(PlatformError) as caught:
            self.runtime.destroy_instance(stable)
        self.assertEqual(caught.exception.code, 'instance_in_use')
