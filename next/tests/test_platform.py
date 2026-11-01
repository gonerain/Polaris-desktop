"""Integration evidence for the new platform, using its public control contract."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from polaris_platform.bootstrap import build
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError
from polaris_platform.transport import ProcessComponent

ROOT = Path(__file__).resolve().parents[1]


def manifest(name):
    return dict(id=name, name=name, version='1', platformApi=1,
                entry=dict(mode='inprocess', factory='unused:create'))


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.runtime = build(json.loads((ROOT / 'config.headless.json').read_text()), ROOT)
        self.add('user', Component)

    def tearDown(self):
        for row in reversed(self.runtime.snapshot()):
            try:
                self.runtime.stop_component(row['id'], force=True)
            except Exception:
                pass

    def add(self, name, factory):
        self.runtime.install(manifest(name), factory)
        self.runtime.start_component(name)
        return self.runtime.component_instance(name)

    def examples(self, process_notes=True):
        from examples.notes.main import create as notes
        from examples.labeler.main import create as labeler
        for name, factory, process in [('notes', notes, process_notes), ('labeler', labeler, True)]:
            directory = ROOT / 'examples' / name
            spec = json.loads((directory / 'manifest.json').read_text())
            if process:
                factory = lambda s=spec, d=directory: ProcessComponent(s, d, timeout=2)
            else:
                spec['entry'] = {'mode': 'inprocess', 'factory': 'examples.notes.main:create'}
            self.runtime.install(spec, factory)
            self.runtime.start_component(spec['id'])

    def call(self, target, operation, params=None, context=None):
        return self.runtime.client('user').call(target, operation, params,
                    context=context or self.runtime.user_context('user'))

    def denied(self, function, code='permission_required'):
        with self.assertRaises(PlatformError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_real_process_chain_permission_revoke_and_provider_equivalence(self):
        for process_notes in (True, False):
            with self.subTest(process_notes=process_notes):
                self.examples(process_notes)
                rt = self.runtime
                rt.grant('user', 'org.example.notes', 'create')
                rt.grant('user', 'org.example.labeler', 'label')
                note = self.call('org.example.notes', 'create', {'title': 'Reading architecture', 'body': 'Portable components'})
                rt.grant('org.example.labeler', 'org.example.notes', 'get')
                self.denied(lambda: self.call('org.example.labeler', 'label', {'note_id': note['id']}))
                rt.grant('user', 'org.example.notes', 'get')
                context = rt.user_context('user')
                tags = self.call('org.example.labeler', 'label', {'note_id': note['id']}, context)
                self.assertIn('architecture', tags['tags'])
                rt.revoke('user', 'org.example.notes', 'get')
                self.denied(lambda: self.call('org.example.labeler', 'label', {'note_id': note['id']}, context))
                error = self.denied(lambda: self.call('org.example.notes', 'create', {'title': ''}), 'handler_error' if process_notes else 'invalid_data')
                self.assertIn('nonempty', str(error))
                for name in ('org.example.labeler', 'org.example.notes'):
                    rt.stop_component(name)
                    # Fresh runtime for provider substitution, leaving the caller code identical.
                if process_notes:
                    self.tearDown()
                    self.setUp()

    def test_restart_preserves_grants_but_invalidates_handle(self):
        def factory():
            c = Component()
            c.operation('get')(lambda p, ctx: {'value': 3})
            return c
        self.add('provider', factory)
        rt = self.runtime
        rt.grant('user', 'provider', 'get')
        client = rt.client('user')
        handle = client.bind('provider', 'get')
        context = rt.user_context('user')
        self.assertEqual(client.invoke(handle, context=context), {'value': 3})
        rt.stop_component('provider')
        self.denied(lambda: client.invoke(handle, context=context), 'unavailable')
        rt.start_component('provider')
        self.denied(lambda: client.invoke(handle, context=context), 'stale_handle')
        self.assertEqual(self.call('provider', 'get'), {'value': 3})

    def test_dynamic_operations_events_and_revocation(self):
        provider = self.add('provider', Component)
        rt = self.runtime
        provider.operation('new')(lambda p, ctx: 'new')
        provider.events['changed'] = dict(major=1, access='read', revision=1)
        provider.port.advertise()
        description = rt.collaboration.describe_target('provider')['description']
        self.assertIn('new', description['operations'])
        self.assertIn('changed', description['events'])
        self.denied(lambda: self.call('provider', 'new'))
        deliveries = []
        client = rt.client('user')
        self.denied(lambda: client.subscribe('provider', 'changed', lambda p, ctx: deliveries.append(p), context=rt.user_context('user')))
        rt.grant('user', 'provider', 'new')
        rt.grant('user', 'provider', 'changed', kind='event')
        self.assertEqual(self.call('provider', 'new'), 'new')
        context = rt.user_context('user')
        client.subscribe('provider', 'changed', lambda p, ctx: deliveries.append(p), context=context)
        provider.port.publish('changed', {'revision': 1}, context=context)
        self.assertEqual(deliveries, [{'revision': 1}])
        rt.revoke('user', 'provider', 'changed', kind='event')
        result = provider.port.publish('changed', {'revision': 2}, context=context)
        self.assertFalse(result[0]['delivered'])
        self.assertEqual(len(deliveries), 1)
        handle = client.bind('provider', 'new')
        provider._operations.pop('new')
        provider.events.pop('changed')
        provider.port.advertise()
        self.denied(lambda: client.invoke(handle, context=context), 'missing_operation')
        self.denied(lambda: provider.port.publish('changed', {}, context=context), 'unavailable')
        description = rt.collaboration.describe_target('provider')['description']
        self.assertNotIn('new', description['operations'])
        self.assertNotIn('changed', description['events'])

    def test_foundation_stop_start_and_replacement(self):
        c = self.add('provider', Component)
        c.operation('get')(lambda p, ctx: 9)
        c.port.advertise()
        rt = self.runtime
        rt.grant('user', 'provider', 'get')
        context = rt.user_context('user')
        from polaris_platform.authorization import Authorization
        from polaris_platform.collaboration import Collaboration
        class AlternateAuthorization(Authorization):
            pass
        class AlternateCollaboration(Collaboration):
            pass
        for name, alternate in [('authorization', AlternateAuthorization), ('collaboration', AlternateCollaboration)]:
            previous = rt.status(name)['instance']
            rt.stop_component(name)
            self.denied(lambda: self.call('provider', 'get', context=context), 'unavailable')
            # Trusted user selects the alternative factory under the same installation.
            rt.replace_component(name, rt.status(name)['manifest'], alternate)
            self.assertNotEqual(previous, rt.status(name)['instance'])
            self.assertEqual(self.call('provider', 'get'), 9)

    def test_dependencies_exit_recovery_optional_and_startup_failure(self):
        provider = self.add('provider', Component)
        provider.operation('get', interface='example.storage')(lambda p, ctx: 'storage')
        provider.port.advertise()
        def dependent(kind):
            c = Component()
            c.dependencies = [dict(kind=kind, target='provider', interface='example.storage', major=1, operations=['use'])]
            c.operation('use')(lambda p, ctx: 'dependent')
            c.operation('own')(lambda p, ctx: 'own')
            return c
        self.add('dependent', lambda: dependent('capability'))
        self.add('optional', lambda: dependent('optional'))
        rt = self.runtime
        for target, operation in [('dependent', 'use'), ('dependent', 'own'), ('optional', 'use')]:
            rt.grant('user', target, operation)
        self.assertEqual(self.call('dependent', 'use'), 'dependent')
        rt.stop_component('provider')
        self.denied(lambda: self.call('dependent', 'use'), 'dependency_unavailable')
        self.assertEqual(self.call('dependent', 'own'), 'own')
        self.assertEqual(self.call('optional', 'use'), 'dependent')
        self.assertFalse(rt.dependency_status('optional')[0]['available'])
        rt.start_component('provider')
        new_provider = rt.component_instance('provider')
        new_provider.operation('get', interface='example.storage')(lambda p, ctx: 'storage')
        new_provider.port.advertise()
        self.assertEqual(self.call('dependent', 'use'), 'dependent')
        rt.stop_component('provider')
        failing = dependent('startup')
        stopped = []
        failing.stop = lambda: stopped.append(True)
        rt.install(manifest('failing'), lambda: failing)
        self.denied(lambda: rt.start_component('failing'), 'dependency_unavailable')
        self.assertTrue(stopped, 'Failed startup must invoke cooperative resource cleanup')
        self.assertNotIn('failing', [r['id'] for r in rt.collaboration.discover()['components']])

    def test_runtime_component_stop_keeps_business_and_recovers_management(self):
        rt = self.runtime
        rt.grant('user', 'runtime', 'list')
        before = rt.status('runtime')['instance']
        self.assertTrue(self.call('runtime', 'list'))
        rt.stop_component('runtime')
        self.denied(lambda: self.call('runtime', 'list'), 'unavailable')
        rt.start_component('runtime')
        self.assertNotEqual(before, rt.status('runtime')['instance'])
        self.assertTrue(self.call('runtime', 'list'))

    def test_process_startup_dependency_failure_reaps_spawned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / 'child.py'
            child.write_text("from polaris_platform.sdk import Component\nc=Component()\nc.dependencies=[{'kind':'startup','target':'missing'}]\nc.run()\n")
            spec = manifest('failed-process')
            spec['entry'] = {'mode': 'process', 'command': ['{python}', str(child)]}
            provider = ProcessComponent(spec, directory, timeout=1)
            self.runtime.install(spec, lambda: provider)
            self.denied(lambda: self.runtime.start_component('failed-process'), 'dependency_unavailable')
            self.assertIsNone(provider.process, 'The child spawned for describe must be reaped on startup failure')
            self.assertIsNone(provider.peer)

    def test_process_crash_keeps_status_inspectable_and_other_components_callable(self):
        self.examples()
        rt = self.runtime
        rt.grant('user', 'org.example.notes', 'list')
        rt.grant('user', 'org.example.labeler', 'get')
        provider = rt.component_instance('org.example.notes')
        failed = threading.Event()
        def failure():
            rt.mark_failed('org.example.notes', 'test crash')
            failed.set()
        provider.set_failure_callback(failure)
        provider.process.kill()
        provider.process.wait(timeout=2)
        self.assertTrue(failed.wait(2))
        self.assertEqual(rt.status('org.example.notes')['state'], 'failed')
        self.assertTrue(rt.snapshot())
        self.denied(lambda: self.call('org.example.notes', 'list'), 'unavailable')
        self.assertEqual(self.call('org.example.labeler', 'get', {'note_id': '1'}), {'note_id': '1', 'tags': []})

    def test_stdio_events_subscribe_publish_unsubscribe_and_scoped_callbacks(self):
        source = """from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
c=Component()
c.events['changed']={'major':1,'access':'read','revision':1}
received=[]
subscriptions=[]
@c.operation('listen')
def listen(target, ctx):
 def event(payload, event_ctx):
  try: event_ctx.call('secret', 'read')
  except PlatformError as error: received.append({'payload':payload,'code':error.code})
  else: received.append({'payload':payload,'code':'unexpected_allow'})
 subscriptions.append(ctx.subscribe(target,'changed',event))
 return len(subscriptions)
@c.operation('emit')
def emit(value, ctx): return ctx.publish('changed',value)
@c.operation('received')
def get_received(): return list(received)
@c.operation('unlisten')
def unlisten(ctx):
 for token in subscriptions: ctx.unsubscribe(token)
 subscriptions.clear()
c.run()
"""
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / 'child.py'
            child.write_text(source)
            for name in ('listener', 'publisher'):
                spec = manifest(name)
                spec['entry'] = {'mode': 'process', 'command': ['{python}', str(child)]}
                self.runtime.install(spec, lambda s=spec: ProcessComponent(s, directory, timeout=2))
                self.runtime.start_component(name)
            secret = self.add('secret', Component)
            secret.operation('read')(lambda p, ctx: 'sensitive')
            secret.port.advertise()
            rt = self.runtime
            for target, operation in [('listener', 'listen'), ('listener', 'received'), ('listener', 'unlisten'), ('publisher', 'emit')]:
                rt.grant('user', target, operation)
            rt.grant('listener', 'secret', 'read')
            self.denied(lambda: self.call('listener', 'listen', {'target': 'publisher'}))
            rt.grant('user', 'publisher', 'changed', kind='event')
            self.call('listener', 'listen', {'target': 'publisher'})
            # Added after subscribe: the publisher's expanded context may not expand a subscriber's saved scope.
            rt.grant('user', 'secret', 'read')
            self.assertTrue(self.call('publisher', 'emit', {'value': 1})[0]['delivered'])
            self.assertEqual(self.call('listener', 'received'), [{'payload': 1, 'code': 'permission_required'}])
            rt.revoke('user', 'publisher', 'changed', kind='event')
            self.assertFalse(self.call('publisher', 'emit', {'value': 2})[0]['delivered'])
            self.call('listener', 'unlisten')
            self.assertEqual(self.call('publisher', 'emit', {'value': 3}), [])
            rt.grant('user', 'publisher', 'changed', kind='event')
            self.call('listener', 'listen', {'target': 'publisher'})
            rt.stop_component('listener')
            self.assertEqual(self.call('publisher', 'emit', {'value': 4}), [])
            rt.stop_component('publisher')

    def test_event_callback_failure_isolated_and_revoked_subscriber_scope_applies(self):
        publisher = self.add('publisher', Component)
        subscriber = self.add('subscriber', Component)
        secret = self.add('secret', Component)
        publisher.events['changed'] = dict(access='read', major=1, revision=1)
        secret.operation('read')(lambda p, ctx: 'sensitive')
        publisher.port.advertise()
        secret.port.advertise()
        rt = self.runtime
        rt.grant('subscriber', 'publisher', 'changed', kind='event')
        rt.grant('subscriber', 'secret', 'read')
        rt.grant('publisher', 'secret', 'read')
        subscription_context = rt.user_context('subscriber')
        def broken(payload, context):
            raise ValueError('callback failed')
        calls = []
        def downstream(payload, context):
            try:
                value = subscriber.port.call('secret', 'read', context=context)
            except PlatformError as error:
                calls.append(error.code)
            else:
                calls.append(value)
        subscriber.port.subscribe('publisher', 'changed', broken, context=subscription_context)
        subscriber.port.subscribe('publisher', 'changed', downstream, context=subscription_context)
        result = publisher.port.publish('changed', {}, context=rt.user_context('publisher'))
        self.assertFalse(result[0]['delivered'])
        self.assertEqual(result[0]['error']['code'], 'component_error')
        self.assertTrue(result[1]['delivered'])
        self.assertEqual(calls, ['sensitive'])
        # The publisher still has read permission. Revoking only the subscriber must remove it from delivery scope.
        rt.revoke('subscriber', 'secret', 'read')
        result = publisher.port.publish('changed', {}, context=rt.user_context('publisher'))
        self.assertTrue(result[1]['delivered'])
        self.assertEqual(calls, ['sensitive', 'permission_required'])

    def test_untrusted_manifest_cannot_request_foundation_control_bindings(self):
        from polaris_platform.bootstrap import default_config
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            spec = manifest('injected')
            spec['entry'] = {'mode': 'inprocess', 'factory': 'binding_fixture:create', 'trustedBindings': True}
            for binding in ({'runtime': True}, {'component': 'authorization'}):
                spec['entry']['kwargs'] = {'runtime': binding}
                (location / 'manifest.json').write_text(json.dumps(spec))
                self.denied(lambda: self.runtime.install_directory(location), 'untrusted_binding')
            (location / 'binding_fixture.py').write_text("from polaris_platform.component import Component\ndef create(runtime, other):\n c=Component()\n c.operation('check')(lambda p,ctx: {'runtime':hasattr(runtime,'install'),'other':hasattr(other,'grant')})\n return c\n")
            spec['entry']['kwargs'] = {'runtime': {'runtime': True}, 'other': {'component': 'authorization'}}
            config = default_config()
            config['components'].append({'manifest': spec, 'directory': directory, 'trustedBindings': True})
            config['start'].append('injected')
            trusted = build(config)
            try:
                trusted.grant('runtime', 'injected', 'check')
                result = trusted.client('runtime').call('injected', 'check', context=trusted.user_context('runtime'))
                self.assertEqual(result, {'runtime': True, 'other': True})
            finally:
                for row in reversed(trusted.snapshot()):
                    if row['state'] == 'running':
                        trusted.stop_component(row['id'])

    def test_required_bootstrap_failure_reaps_previously_started_processes(self):
        from polaris_platform.bootstrap import default_config
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            (location / 'child.py').write_text("import os,sys\nfrom pathlib import Path\nfrom polaris_platform.sdk import Component\nPath(sys.argv[1]+'.pid').write_text(str(os.getpid()))\nc=Component()\nif sys.argv[1]=='bad': c.dependencies=[{'kind':'startup','target':'missing'}]\nc.run()\n")
            config = default_config()
            for identity in ('good', 'bad'):
                spec = manifest(identity)
                spec['entry'] = {'mode': 'process', 'command': ['{python}', 'child.py', identity]}
                config['components'].append({'manifest': spec, 'directory': directory})
                config['start'].append(identity)
            config['required'].append('bad')
            self.denied(lambda: build(config), 'dependency_unavailable')
            for identity in ('good', 'bad'):
                pid = int((location / (identity + '.pid')).read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_public_installation_export_import_preserves_control_metadata(self):
        from polaris_platform.runtime import Runtime
        source, replacement = Runtime(), Runtime()
        source.install(manifest('portable'), Component, installation_id='stable-install',
                       directory=ROOT / 'examples', autostart=True, trusted_bindings=True)
        records = source.export_installations()
        replacement.import_installations(records, lambda spec: Component)
        self.assertEqual(replacement.export_installations(), records)
        self.assertEqual(records[0]['installationId'], 'stable-install')
        self.assertTrue(records[0]['autostart'])
        self.assertTrue(records[0]['trustedBindings'])
        self.assertEqual(records[0]['directory'], str(ROOT / 'examples'))

    def test_event_delivery_rechecks_unsubscribe_and_withdraw_between_callbacks(self):
        publisher = self.add('publisher', Component)
        publisher.events['changed'] = dict(access='read', major=1, revision=1)
        publisher.port.advertise()
        rt = self.runtime
        rt.grant('user', 'publisher', 'changed', kind='event')
        context = rt.user_context('user')
        client = rt.client('user')
        delivered = []
        second = []
        first = client.subscribe('publisher', 'changed',
                   lambda payload, ctx: client.unsubscribe(second[0]), context=context)
        second.append(client.subscribe('publisher', 'changed', lambda p, c: delivered.append('late'), context=context))
        result = publisher.port.publish('changed', {}, context=context)
        self.assertEqual(len(result), 1)
        self.assertEqual(delivered, [])
        client.unsubscribe(first)
        def withdraw(payload, ctx):
            publisher.events.pop('changed')
            publisher.port.advertise()
        client.subscribe('publisher', 'changed', withdraw, context=context)
        client.subscribe('publisher', 'changed', lambda p, c: delivered.append('withdrawn'), context=context)
        result = publisher.port.publish('changed', {}, context=context)
        self.assertTrue(result[0]['delivered'])
        self.assertFalse(result[1]['delivered'])
        self.assertEqual(result[1]['error']['code'], 'unavailable')
        self.assertEqual(delivered, [])

    def test_queued_context_cannot_be_modified_with_dataclass_replace(self):
        from dataclasses import replace
        provider = self.add('provider', Component)
        provider.operation('get')(lambda p, ctx: 'allowed')
        provider.operation('extra')(lambda p, ctx: 'extra')
        provider.port.advertise()
        rt = self.runtime
        rt.grant('user', 'provider', 'get')
        saved = rt.user_context('user')
        # There is no active handler here: this models queued work retaining a saved context.
        rt.grant('user', 'provider', 'extra')
        expanded = rt.user_context('user')
        modifications = [dict(scope=expanded.scope), dict(source='background'), dict(origin='provider'),
                         dict(request_id='invented-request'), dict(caller='provider')]
        for change in modifications:
            with self.subTest(change=change):
                self.denied(lambda: self.call('provider', 'get', context=replace(saved, **change)), 'invalid_context')
        self.denied(lambda: self.call('provider', 'extra', context=saved))
        self.assertEqual(self.call('provider', 'get', context=saved), 'allowed')

    def test_headless_cli_without_qt_or_old_packages(self):
        script = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in ('PySide6', 'polaris', 'prototypes'):
   raise ImportError('blocked ' + fullname)
sys.meta_path.insert(0, Block())
from polaris_platform.__main__ import main
raise SystemExit(main())
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({r['id'] for r in json.loads(result.stdout)}, {'authorization', 'collaboration', 'runtime'})
