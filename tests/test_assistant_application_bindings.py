"""Exercise the shipped Agent package, not only the in-tree component."""
import importlib.util
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from polaris_platform.application import ApplicationDefinition
from polaris_platform.bootstrap import build, default_config
from polaris_platform.protocol import PlatformError


class PackagedAgentBindingsTests(unittest.TestCase):
    def test_application_can_bind_status_and_reply_without_bypassing_permissions(self):
        name = '_packaged_agent_binding_test'
        root = Path(__file__).resolve().parents[1] / 'packages/assistant/polaris_assistant'
        spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(lambda: [sys.modules.pop(key, None) for key in list(sys.modules)
                                 if key == name or key.startswith(name + '.')])
        spec.loader.exec_module(module)

        class Engine:
            def run(self, text, history, tools, cancel):
                return module.AgentResult('test answer', [])

        runtime = build(default_config())
        runtime.install(dict(id='assistant', name='Agent', version='1', platformApi=1,
                             entry=dict(mode='inprocess')), lambda: module.Assistant(Engine()))
        runtime.start_component('assistant')
        app_id = uuid4().hex
        runtime.register_application_principal(app_id)
        try:
            status = runtime.status('assistant')
            identity = status['instanceId']
            runtime.register_application_bindings(app_id, [identity])
            client, context = runtime.application_client(app_id), runtime.application_context(app_id)
            bindings = {}
            for alias, operation in (('agentStatus', 'status'), ('agentReply', 'reply')):
                metadata = status['description']['operations'][operation]
                self.assertEqual(metadata['applicationBinding'], 'instance')
                self.assertEqual(metadata['provides'], 'polaris.agent.' + operation + '@1')
                handle = client.bind(identity, operation)
                bindings[alias] = dict(target=identity, instanceId=identity,
                                       installationId=status['installationId'], operation=operation,
                                       semantic=list(handle.semantic))
            app = ApplicationDefinition('Test', application_id=app_id, bindings=bindings)
            session = app.open(client, context, runtime.status)
            with self.assertRaises(PlatformError) as error:
                session.call('agentReply', dict(text='hello', allowed=[]))
            self.assertIn(error.exception.code, ('permission_required', 'permission_denied'))
            for operation in ('status', 'reply'):
                runtime.grant(app_id, identity, operation)
            # Refresh the scoped context after the explicit grants.
            session = app.open(client, runtime.application_context(app_id), runtime.status)
            self.assertTrue(session.call('agentStatus', {})['ready'])
            self.assertEqual(session.call('agentReply', dict(text='hello', allowed=[]))['text'], 'test answer')
        finally:
            runtime.unregister_application_principal(app_id)
            for row in reversed(runtime.snapshot()):
                if row['state'] == 'running':
                    runtime.stop_component(row['id'], persist=False)
