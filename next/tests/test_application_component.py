"""Applications use component execution and retain durable authorization identity."""
import json
from pathlib import Path
import tempfile
import unittest

from polaris_platform.application import Application, ApplicationDefinition, ApplicationStore
from polaris_platform.bootstrap import build
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError
from polaris_platform.sdk import Application as SDKApplication

ROOT = Path(__file__).resolve().parents[1]


class ApplicationComponentTests(unittest.TestCase):
    def setUp(self):
        self.runtime = build(json.loads((ROOT / 'config.headless.json').read_text()), ROOT)

    def tearDown(self):
        for row in reversed(self.runtime.snapshot()):
            self.runtime.stop_component(row['id'], force=True)

    def assert_code(self, code, callback):
        with self.assertRaises(PlatformError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def test_real_graph_provider_and_shared_lifecycle(self):
        definition = ApplicationDefinition('Counter')
        stopped = []
        def factory():
            app = Application(definition=definition, on_stop=lambda: stopped.append(True))
            app.operation('echo', applicationBinding='instance')(lambda params, ctx: params)
            return app
        identity = self.runtime.ensure_application(definition, factory=factory)
        self.runtime.start_application(identity)
        self.assertIsInstance(self.runtime.application_component(identity), Component)
        status = self.runtime.status(identity)
        self.assertEqual(status['instanceId'], definition.id)
        self.assertIn('echo', status['description']['operations'])
        self.runtime.grant(identity, identity, 'echo')
        client = self.runtime.application_client(identity)
        context = self.runtime.application_context(identity)
        self.assertEqual(client.call(identity, 'echo', {'value': 3}, context), {'value': 3})
        self.runtime.stop_component(identity)
        self.assertEqual(stopped, [True])
        self.assert_code('stale_instance', lambda: client.bind(identity, 'echo'))
        self.assert_code('invalid_context', lambda: self.runtime.validate_context(context))
        self.runtime.start_component(identity)
        self.assertNotEqual(status['runId'], self.runtime.status(identity)['runId'])
        self.assert_code('stale_instance', lambda: client.bind(identity, 'echo'))

    def test_regrant_does_not_restore_old_context(self):
        definition = ApplicationDefinition('Revocable')
        self.runtime.ensure_application(definition)
        self.runtime.start_application(definition.id)
        context = self.runtime.application_context(definition.id)
        client = self.runtime.application_client(definition.id)
        self.runtime.revoke_application_authority(definition.id)
        self.runtime.start_application(definition.id)
        self.assert_code('invalid_context', lambda: self.runtime.validate_context(context))
        self.assert_code('stale_instance', lambda: self.runtime.validate_client(client))
        self.runtime.validate_context(self.runtime.application_context(definition.id))

    def test_definition_restore_preserves_identity_grants_and_data_location(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ApplicationStore(Path(directory) / 'applications')
            definition = ApplicationDefinition('Legacy', config={'retained': True})
            store.save(definition)
            restored = store.load(definition.id)
            self.assertIsInstance(restored, ApplicationDefinition)
            self.assertEqual(restored.as_dict(), definition.as_dict())
            self.runtime.ensure_application(restored, restore=True)
            self.runtime.start_application(restored.id)
            self.assertNotIn(restored.id, [row['manifest']['id'] for row in self.runtime.export_installations()])
            self.runtime._state_dir = Path(directory)
            self.assertEqual(self.runtime.component_data_directory(restored.id), Path(directory) / 'application-data' / restored.id)

    def test_restore_existing_authorization_and_instance_storage(self):
        definition = ApplicationDefinition('Restored provider')
        def factory():
            app = Application(definition=definition)
            app.operation('read', applicationBinding='instance')(lambda params, ctx: 'preserved')
            return app
        self.runtime.ensure_application(definition, factory=factory)
        self.runtime.start_application(definition.id)
        self.runtime.grant(definition.id, definition.id, 'read')
        saved = self.runtime.authorization.export_records()
        self.runtime.stop_application(definition.id)
        restored = build(json.loads((ROOT / 'config.headless.json').read_text()), ROOT)
        try:
            restored.authorization.import_records(saved)
            restored.ensure_application(definition, factory=factory, restore=True)
            restored.start_application(definition.id)
            self.assertEqual(restored.application_client(definition.id).call(
                definition.id, 'read', context=restored.application_context(definition.id)), 'preserved')
            with tempfile.TemporaryDirectory() as directory:
                restored._instance_storage = Path(directory) / 'instances.json'
                restored._persist_instances()
                self.assertEqual(json.loads(restored._instance_storage.read_text())['instances'], [])
        finally:
            for row in reversed(restored.snapshot()):
                restored.stop_component(row['id'], force=True)

    def test_host_data_path_type_and_existing_registration_guard(self):
        definition = ApplicationDefinition('Packaged')
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'existing-canvas' / 'application-data' / definition.id
            self.runtime.ensure_application(definition, component_type='org.example.editor',
                                            version='2.0', data_directory=data)
            self.runtime.start_application(definition.id)
            self.assertEqual(self.runtime.status(definition.id)['componentType'], 'org.example.editor')
            self.assertEqual(self.runtime.status(definition.id)['instanceId'], definition.id)
            self.assertEqual(self.runtime.component_data_directory(definition.id), data)
            self.assert_code('application_management_required', lambda: self.runtime.uninstall_component(definition.id))
            self.assert_code('application_background_unsupported', lambda: self.runtime.background_context(definition.id))
            from polaris_platform.runtime import _active
            token = _active.set(object())
            try:
                self.assert_code('permission_denied', lambda: self.runtime.register_application_principal(definition.id))
                self.assert_code('permission_denied', lambda: self.runtime.start_application(definition.id))
            finally:
                _active.reset(token)
            self.runtime.unregister_application_principal(definition.id)
            self.assert_code('not_installed', lambda: self.runtime.grant(definition.id, 'runtime', 'status'))

    def test_sdk_subclass_lifecycle_and_documented_event_publication(self):
        lifecycle = []
        class TextApplication(SDKApplication):
            def __init__(self, definition):
                super().__init__(definition=definition)
                self.event('changed')
                @self.operation('tidy', access='read', applicationBinding='instance')
                def tidy(text, ctx):
                    result = ' '.join(text.split())
                    ctx.publish('changed', {'text': result})
                    return {'text': result}

            def start(self, port):
                super().start(port)
                lifecycle.append(('start', self.port is port))

            def stop(self):
                super().stop()
                lifecycle.append(('stop', self.port is None))

        definition = ApplicationDefinition('文本应用')
        self.runtime.ensure_application(definition, factory=lambda: TextApplication(definition),
                                        component_type='org.example.text-application', version='1.0.0')
        self.runtime.start_application(definition.id)
        self.runtime.grant(definition.id, definition.id, 'tidy')
        from unittest.mock import patch
        collaboration = self.runtime.collaboration
        with patch.object(collaboration, 'publish', wraps=collaboration.publish) as publication:
            result = self.runtime.application_client(definition.id).call(definition.id, 'tidy',
                {'text': ' hello   world '}, self.runtime.application_context(definition.id))
            self.assertEqual(result, {'text': 'hello world'})
            self.assertEqual(publication.call_args.args[:3],
                             (definition.id, 'changed', {'text': 'hello world'}))
        self.runtime.stop_component(definition.id)
        self.runtime.start_component(definition.id)
        self.assertEqual(lifecycle, [('start', True), ('stop', True), ('start', True)])

    def test_sdk_application_keyword_handler(self):
        app = SDKApplication('SDK app')
        @app.operation('echo', applicationBinding='instance')
        def echo(value, ctx):
            return {'value': value, 'context': ctx is not None}
        self.runtime.ensure_application(app.definition, factory=lambda: app)
        self.runtime.start_application(app.id)
        self.runtime.grant(app.id, app.id, 'echo')
        # Ordinary user invocation uses the same collaboration directory.
        context = self.runtime.user_context(app.id)
        self.assertEqual(self.runtime.client(app.id).call(app.id, 'echo', {'value': 9}, context),
                         {'value': 9, 'context': True})
