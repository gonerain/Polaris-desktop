"""Durable task delegation retains installation ownership and exact authority."""
import json
from pathlib import Path
import tempfile
import unittest
from polaris_platform.bootstrap import build, default_config
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError


class TaskResumeTests(unittest.TestCase):
    def stop(self, runtime):
        for row in reversed(runtime.snapshot()):
            if row['state'] == 'running':
                runtime.stop_component(row['id'], persist=False)

    def test_restart_retains_only_selected_authority_and_honors_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = build(default_config(), state_dir=directory)
            for name in ('owner', 'worker', 'other'):
                runtime.install(dict(id=name, name=name, version='1', platformApi=1,
                    entry=dict(mode='inprocess', factory='polaris_platform.sdk:Component')), Component, autostart=True)
                runtime.start_component(name)
            runtime.grant('owner', 'runtime', 'list')
            runtime.grant('owner', 'collaboration', 'discover')
            runtime.client('worker').remember_task('reply', [('runtime', 'list')], runtime.user_context('owner'))
            self.stop(runtime)
            # Previous releases persisted user delegations without a source field.
            path = Path(directory) / 'tasks.json'
            records = json.loads(path.read_text())
            for record in records.values():
                record.pop('source')
            path.write_text(json.dumps(records))
            runtime = build(default_config(), state_dir=directory)
            try:
                worker = runtime.client('worker')
                context = worker.resume_task('reply')
                self.assertEqual(context.source, 'user')
                self.assertTrue(worker.call('runtime', 'list', context=context))
                with self.assertRaises(PlatformError):
                    worker.call('collaboration', 'discover', context=context)
                self.assertIsNone(runtime.client('other').resume_task('reply'))
                runtime.revoke('owner', 'runtime', 'list')
                with self.assertRaises(PlatformError) as denied:
                    worker.call('runtime', 'list', context=worker.resume_task('reply'))
                self.assertEqual(denied.exception.code, 'permission_required')
                worker.forget_task('reply', runtime.user_context('owner'))
                self.assertIsNone(worker.resume_task('reply'))
            finally:
                self.stop(runtime)

    def test_background_delegation_retains_source_and_limited_scope_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = build(default_config(), state_dir=directory)
            for name in ('owner', 'worker'):
                runtime.install(dict(id=name, name=name, version='1', platformApi=1,
                    entry=dict(mode='inprocess', factory='polaris_platform.sdk:Component')), Component, autostart=True)
                runtime.start_component(name)
            runtime.grant('owner', 'runtime', 'list', background=True)
            runtime.grant('owner', 'collaboration', 'discover', background=True)
            runtime.grant('owner', 'runtime', 'list')
            runtime.client('worker').remember_task('reply', [('runtime', 'list')], runtime.background_context('owner'))
            self.stop(runtime)
            runtime = build(default_config(), state_dir=directory)
            try:
                worker = runtime.client('worker')
                context = worker.resume_task('reply')
                self.assertEqual(context.source, 'background')
                self.assertEqual(context.origin, 'owner')
                self.assertEqual(len(context.scope), 1)
                self.assertTrue(worker.call('runtime', 'list', context=context))
                with self.assertRaises(PlatformError):
                    worker.call('collaboration', 'discover', context=context)
                runtime.revoke('owner', 'runtime', 'list', background=True)
                with self.assertRaises(PlatformError) as denied:
                    worker.call('runtime', 'list', context=worker.resume_task('reply'))
                self.assertEqual(denied.exception.code, 'permission_required')
                runtime.grant('owner', 'runtime', 'list', background=True)
                self.assertTrue(worker.call('runtime', 'list', context=worker.resume_task('reply')))
            finally:
                self.stop(runtime)

    def test_setup_requires_authority_in_both_original_scope_and_live_grants(self):
        runtime = build(default_config())
        for name in ('owner', 'worker'):
            runtime.install(dict(id=name, name=name, version='1', platformApi=1,
                                 entry=dict(mode='inprocess')), Component)
            runtime.start_component(name)
        try:
            worker = runtime.client('worker')
            original = runtime.background_context('owner')
            runtime.grant('owner', 'runtime', 'list', background=True)
            with self.assertRaises(PlatformError) as denied:
                worker.remember_task('reply', [('runtime', 'list')], original)
            self.assertEqual(denied.exception.code, 'permission_required')
            self.assertIsNone(worker.resume_task('reply'))
            authorized = runtime.background_context('owner')
            runtime.revoke('owner', 'runtime', 'list', background=True)
            runtime.grant('owner', 'runtime', 'list')
            with self.assertRaises(PlatformError) as denied:
                worker.remember_task('reply', [('runtime', 'list')], authorized)
            self.assertEqual(denied.exception.code, 'permission_required')
            self.assertIsNone(worker.resume_task('reply'))
        finally:
            self.stop(runtime)

    def test_task_cannot_replace_authority_inside_active_handler(self):
        runtime = build(default_config())
        component = Component()
        component.operation('resume')(lambda: component.port.resume_task('reply'))
        runtime.install(dict(id='worker', name='Worker', version='1', platformApi=1,
                             entry=dict(mode='inprocess')), lambda: component)
        runtime.start_component('worker')
        try:
            runtime.grant('worker', 'worker', 'resume')
            runtime.grant('worker', 'runtime', 'list')
            worker = runtime.client('worker')
            worker.remember_task('reply', [('runtime', 'list')], runtime.user_context('worker'))
            with self.assertRaises(PlatformError) as denied:
                worker.call('worker', 'resume', context=runtime.user_context('worker'))
            self.assertEqual(denied.exception.code, 'scope_escalation')
        finally:
            self.stop(runtime)
