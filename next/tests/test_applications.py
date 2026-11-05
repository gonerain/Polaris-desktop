"""Applications compose ordinary calls without obtaining management authority."""
import json
from pathlib import Path
import tempfile
import unittest

from polaris_platform.application import Application, ApplicationStore
from polaris_platform.bootstrap import build
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def manifest(name):
    return dict(id=name, name=name, version='1', platformApi=1,
                entry=dict(mode='inprocess', factory='unused:create'))


class ApplicationsTests(unittest.TestCase):
    def setUp(self):
        self.runtime = build(json.loads((ROOT / 'config.headless.json').read_text()), ROOT)
        self.runtime.install(manifest('user'), Component)
        def provider():
            c = Component()
            c.operation('echo', applicationBinding='instance')(lambda p, ctx: dict(p, origin=ctx.origin))
            return c
        self.runtime.install(manifest('provider'), provider)
        self.runtime.start_component('user')
        self.runtime.start_component('provider')
        from uuid import uuid4
        self.app_id = uuid4().hex
        self.runtime.register_application_principal(self.app_id)
        self.client = self.runtime.application_client(self.app_id)
        status = self.runtime.status('provider')
        self.binding = dict(target='provider', installationId=status.get('installationId', status['installation']),
                            instanceId=status.get('instanceId', status['installation']), operation='echo',
                            semantic=list(self.client.bind('provider', 'echo').semantic))
        self.app = Application('Echo composition', {'echo': self.binding}, config={'label': 'demo'},
                               flows={'repeat': [{'alias': 'echo', 'input': 'previous'}]},
                               pages=[{'id': 'main', 'title': 'Echo', 'action': 'repeat'}], application_id=self.app_id)

    def tearDown(self):
        for row in reversed(self.runtime.snapshot()):
            try:
                self.runtime.stop_component(row['id'], force=True)
            except Exception:
                pass

    def session(self):
        return self.app.open(self.client, self.runtime.application_context(self.app_id), self.runtime.status)

    def assert_code(self, code, callback):
        with self.assertRaises(PlatformError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def test_calls_require_user_authority_and_honor_live_revocation(self):
        self.assert_code('permission_required', lambda: self.session().call('echo'))
        self.runtime.grant(self.app_id, 'provider', 'echo')
        session = self.session()
        self.assertEqual(session.run('repeat', {'value': 4}), {'value': 4, 'origin': self.app_id})
        self.runtime.revoke(self.app_id, 'provider', 'echo')
        self.assert_code('permission_required', lambda: session.call('echo'))

    def test_restart_rebinds_same_stable_instance_stop_keeps_shared_provider(self):
        self.runtime.grant(self.app_id, 'provider', 'echo')
        session = self.session()
        self.runtime.stop_component('provider')
        self.assert_code('application_binding_unavailable', lambda: session.call('echo'))
        self.runtime.start_component('provider')
        self.assertEqual(session.call('echo')['origin'], self.app_id)
        session.stop()
        self.assertEqual(self.runtime.status('provider')['state'], 'running')
        self.assert_code('application_closed', lambda: session.call('echo'))

    def test_identity_mismatch_never_selects_another_provider(self):
        self.app.bindings['echo']['instanceId'] = 'deleted-instance'
        self.app.bindings['echo']['semantic'][0] = 'deleted-instance'
        self.assert_code('application_binding_unavailable', lambda: self.session().call('echo'))
        semantic = list(self.binding['semantic'])
        semantic[5] += 1
        self.app.bindings['echo'] = dict(self.binding, semantic=semantic)
        self.assert_code('application_binding_unavailable', lambda: self.session().call('echo'))

    def test_definition_roundtrip_and_session_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.json'
            self.app.save(path)
            restored = Application.load(path)
        self.assertEqual(restored.as_dict(), self.app.as_dict())
        session = self.session()
        self.app.bindings.clear()
        self.assertIn('echo', session.application.bindings)

    def test_provider_opt_in_is_rechecked_on_every_execution(self):
        self.runtime.grant(self.app_id, 'provider', 'echo')
        session = self.session()
        component = self.runtime.component_instance('provider')
        component._operations['echo'].pop('applicationBinding')
        component.port.advertise()
        self.assert_code('application_binding_unsupported', lambda: session.call('echo'))
        component._operations['echo']['applicationBinding'] = 'instance'
        component.port.advertise()
        self.assertEqual(session.call('echo')['origin'], self.app_id)

    def test_other_principals_cannot_execute_application(self):
        self.assert_code('application_identity_mismatch', lambda: self.app.open(
            self.runtime.client('user'), self.runtime.user_context('user'), self.runtime.status))

    def test_store_is_application_owned_and_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ApplicationStore(directory)
            store.save(self.app)
            self.assertEqual(store.list(), [self.app.as_dict()])
            self.assert_code('invalid_application', lambda: store.load('../escape'))
            store.delete(self.app.id)
            self.assertEqual(store.list(), [])

    def test_resource_scope_rejected(self):
        for key in ('resource', 'scope'):
            self.assert_code('unsupported_resource_scope', lambda: Application('Invalid', {'echo': dict(self.binding, **{key: {'robot_id': 'one'}})}))
