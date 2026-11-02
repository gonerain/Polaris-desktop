"""Resolve real local and stdio plugins without relying on implementation names."""
from pathlib import Path
import tempfile
import unittest

from polaris_platform.bootstrap import build, default_config
from polaris_platform.protocol import PlatformError
from polaris_platform.sdk import Component
from polaris_platform.transport import ProcessComponent
from examples.labeler.main import create as labeler

ROOT = Path(__file__).resolve().parents[1]


def manifest(name):
    return dict(id=name, name=name, version='1', platformApi=1,
                entry=dict(mode='inprocess', factory='examples.notes.main:create'))


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.rt = build(default_config(), ROOT)
        self.addCleanup(self.stop)

    def stop(self):
        for record in reversed(self.rt.snapshot()):
            if record['state'] == 'running':
                self.rt.stop_component(record['id'], persist=False)

    def add(self, name, component):
        self.rt.install(manifest(name), lambda: component)
        self.rt.start_component(name)
        return component

    def call(self, target, name, params=None, context=None):
        return self.rt.client('runtime').call(target, name, params, context or self.rt.user_context('runtime'))

    def grant(self, target, name, kind='operation'):
        self.rt.grant('runtime', target, name, kind)

    def meta(self, target, name, group='operations'):
        return self.rt.status(target)['description'][group][name]

    def select(self, consumer, operation, alias, provider):
        self.rt.select_provider(consumer, 'operation', operation, alias, self.rt.status(provider)['installation'],
                                self.rt.status(consumer)['installation'])

    def assert_code(self, code, callback):
        with self.assertRaises(PlatformError) as error:
            callback()
        self.assertEqual(error.exception.code, code)
        return error.exception.details

    def process(self):
        spec = manifest('remote')
        spec['entry'] = dict(mode='process', command=['{python}', 'contract_plugin.py'])
        self.rt.install(spec, lambda: ProcessComponent(spec, ROOT / 'tests/fixtures'))
        self.rt.start_component('remote')

    def test_runtime_publication_withdrawal_and_replacement(self):
        self.add('labels', labeler())
        self.process()
        for name in ('label', 'get'):
            self.grant('labels', name)
        self.grant('remote', 'configure')
        self.call('remote', 'configure', {'enabled': True})
        candidates = self.rt.collaboration.providers('notes.read@1')
        self.assertEqual([(row['target'], row['name']) for row in candidates], [('remote', 'fetch')])
        self.assertEqual(self.rt.collaboration.providers('example.changed@1', 'event')[0]['name'], 'news')
        old = self.rt.user_context('runtime')
        run = lambda ctx=None: self.call('labels', 'label', {'note_id': '1'}, ctx)
        self.assert_code('permission_required', lambda: run(old))
        self.grant('remote', 'fetch')
        self.assert_code('permission_required', lambda: run(old))
        tags = run()
        self.call('remote', 'configure', {'enabled': False})
        self.assert_code('dependency_unavailable', run)
        self.assertEqual(self.call('labels', 'get', {'note_id': '1'}), tags)
        self.assertEqual(self.rt.collaboration.providers('example.changed@1', 'event'), [])
        other = self.add('other', Component())
        other.operation('load', provides='notes.read@1')(lambda id: dict(title='Alternative provider', body=''))
        self.assert_code('dependency_unavailable', run)  # Offline selection stays pinned.
        self.call('remote', 'configure', {'enabled': True})
        self.assertEqual(run(), tags)
        previous = self.rt.user_context('runtime')
        self.select('labels', 'label', 'note', 'other')
        self.assert_code('permission_required', lambda: run(previous))
        self.grant('other', 'load')
        self.assertIn('alternative', run()['tags'])
        current = self.rt.user_context('runtime')
        self.rt.revoke('runtime', 'other', 'load')
        self.assert_code('permission_required', lambda: run(current))

    def test_stdio_required_subscription_and_nested_event_context(self):
        source = self.add('source', Component())
        source.event('arrived', provides='example.incoming@1')
        source.operation('identity', provides='example.name@1')(lambda: 'source')
        self.process()
        self.grant('remote', 'listen')
        self.grant('remote', 'received')
        self.grant('source', 'identity')
        self.assert_code('permission_required', lambda: self.call('remote', 'listen'))
        self.grant('source', 'arrived', 'event')
        self.call('remote', 'listen')
        context = self.rt.user_context('runtime')
        self.assertTrue(source.port.publish('arrived', 1, context)[0]['delivered'])
        self.rt.revoke('runtime', 'source', 'identity')
        self.assertFalse(source.port.publish('arrived', 2, context)[0]['delivered'])
        self.assertEqual(self.call('remote', 'received'), [[1, 'source']])

    def test_transitive_cycle_optional_version_and_invalid_registration(self):
        first = self.add('a', Component())
        second = self.add('b', Component())
        first.operation('top', provides='chain.top@1', requires={'b': 'chain.mid@1'})(lambda ctx: ctx.call_required('b'))
        second.operation('mid', provides='chain.mid@1', requires={'a': 'chain.top@1'})(lambda: 'mid')
        reason = self.meta('a', 'top')['reason']
        self.assertEqual(reason['code'], 'dependency_cycle')
        self.assertEqual({node[0] for node in reason['path']}, {'a', 'b'})
        second.operation('mid', provides='chain.mid@1', requires={'leaf': 'chain.leaf@1'})(lambda: 'mid')
        self.assertEqual(self.meta('a', 'top')['reason']['contract'], 'chain.leaf@1')
        second.operation('leaf2', major=2, provides='chain.leaf@2')(lambda: 'v2')
        self.assertEqual(self.meta('a', 'top')['reason']['offered'], ['chain.leaf@2'])
        second.operation('leaf', provides='chain.leaf@1')(lambda: 'v1')
        self.assertTrue(self.meta('a', 'top').get('available', True))
        self.assert_code('invalid_description', lambda: second.operation('leaf', provides='bad')(lambda: 'wrong'))
        self.grant('b', 'leaf')
        self.assertEqual(self.call('b', 'leaf'), 'v1')
        first.operation('partial', requires={'extra': {'contract': 'missing.optional@1', 'optional': True}})(lambda: 'ready')
        self.grant('a', 'partial')
        self.assertEqual(self.call('a', 'partial'), 'ready')
        first.event('change', provides='example.change@1', requires={'b': 'chain.mid@1'})
        second.withdraw_operation('mid')
        self.assertFalse(self.meta('a', 'change', 'events')['available'])
        self.assertEqual(self.meta('a', 'top')['reason']['contract'], 'chain.mid@1')

    def test_unique_ready_provider_and_old_handle_after_republication(self):
        good = self.add('good', Component())
        blocked = self.add('blocked', Component())
        good.operation('fetch', provides='example.read@1')(lambda: 'good')
        blocked.operation('load', provides='example.read@1', requires={'db': 'example.db@1'})(lambda: 'blocked')
        client = self.add('client', Component())
        for name in ('first', 'second'):
            client.operation(name, requires={'data': 'example.read@1'})(lambda ctx: ctx.call_required('data'))
            self.grant('client', name)
        self.grant('good', 'fetch')
        self.assertEqual(self.call('client', 'first'), 'good')
        previous = self.rt.client('runtime').bind('good', 'fetch')
        good.withdraw_operation('fetch')
        good.operation('fetch', provides='example.read@1')(lambda: 'restored')
        self.assert_code('stale_handle', lambda: self.rt.client('runtime').invoke(previous, context=self.rt.user_context('runtime')))
        self.assertEqual(self.call('client', 'first'), 'restored')
        blocked.operation('db', provides='example.db@1')(lambda: None)
        self.select('client', 'second', 'data', 'blocked')
        self.grant('blocked', 'load')
        self.assertEqual(self.call('client', 'second'), 'blocked')
        self.assertEqual(self.call('client', 'first'), 'restored')

    def test_new_contract_cannot_borrow_a_previously_granted_local_name(self):
        provider = self.add('p', Component())
        provider.operation('act', provides='example.old@1')(lambda: 'old')
        self.grant('p', 'act')
        old = self.rt.user_context('runtime')
        self.assert_code('invalid_description', lambda: provider.operation('act', provides='example.new@1')(lambda: 'new'))
        self.assertEqual(self.call('p', 'act', context=old), 'old')
        provider.operation('act', provides='example.new@1', revision=2)(lambda: 'new')
        self.assert_code('permission_required', lambda: self.call('p', 'act', context=old))
        self.grant('p', 'act')
        self.assertEqual(self.call('p', 'act'), 'new')
        self.assert_code('permission_required', lambda: self.call('p', 'act', context=old))

    def test_choices_per_consumer_survive_restart_and_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            config = default_config()
            for name in ('one', 'two', 'reader1', 'reader2'):
                spec = manifest(name)
                if name.startswith('reader'):
                    spec['entry']['factory'] = 'examples.labeler.main:create'
                config['components'].append({'manifest': spec})
                config['start'].append(name)
            self.rt = build(config, ROOT, directory)
            for consumer, provider in [('reader1', 'one'), ('reader2', 'two')]:
                self.assertEqual(self.meta(consumer, 'label')['reason']['code'], 'selection_required')
                self.select(consumer, 'label', 'note', provider)
            self.stop()
            self.rt = build(config, ROOT, directory)
            try:
                for consumer, provider in [('reader1', 'one'), ('reader2', 'two')]:
                    self.assertEqual(self.meta(consumer, 'label')['bindings']['note']['endpoint']['target'], provider)
                notes = self.rt.component_instance('one')
                notes.withdraw_operation('get')
                self.assert_code('invalid_description', lambda: notes.operation('get', provides='other.contract@1')(lambda: None))
                self.rt.uninstall_component('one')
                self.add('one', Component()).operation('get', provides='notes.read@1')(lambda id: {})
                self.assertEqual(self.meta('reader1', 'label')['reason']['code'], 'selected_provider_unavailable')
                self.assertTrue(self.meta('reader2', 'label').get('available', True))
            finally:
                self.stop()
