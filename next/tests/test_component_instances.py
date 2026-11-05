"""Stable identities and isolated authorization across component lifecycles."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from polaris_platform.bootstrap import build, default_config
from polaris_platform.protocol import PlatformError
ROOT = Path(__file__).resolve().parents[1]

class StableInstanceTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop('isolation_example', None)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        plugin = self.base / 'plugin'; plugin.mkdir()
        (plugin / 'isolation_example.py').write_text('''from polaris_platform.component import Component\nclass Example(Component):\n def __init__(self, instance_context=None):\n  super().__init__(); self.ctx=instance_context; self.operation("read",applicationBinding="instance")(lambda p,c: self.ctx or {"legacy":True})\ndef create(instance_context=None): return Example(instance_context)\n''')
        self.config = default_config()
        self.config['components'].append(dict(manifest=dict(id='example',name='Example',version='1',platformApi=1,entry=dict(mode='inprocess',factory='isolation_example:create'),instances=dict(mode='multiple')), directory=str(plugin)))
        self.runtime = build(self.config, ROOT, state_dir=self.base/'state')
        (plugin / 'manifest.json').write_text(json.dumps(self.config['components'][-1]['manifest']))
        self.runtime.start_component('example')
    def tearDown(self):
        for row in reversed(self.runtime.snapshot()):
            try: self.runtime.stop_component(row['id'],force=True,persist=False)
            except Exception: pass
        sys.modules.pop('isolation_example', None)
        self.tmp.cleanup()
    def assert_code(self, code, action):
        with self.assertRaises(PlatformError) as caught: action()
        self.assertEqual(caught.exception.code, code)
    def test_isolation_and_restart(self):
        rt=self.runtime; first=rt.create_instance('example',config={'label':'one'}); second=rt.create_instance('example',config={'label':'two'})
        rt.start_instance(first); rt.start_instance(second)
        default=rt.status('example'); self.assertEqual(default['installationId'],default['instanceId'])
        self.assertEqual(rt.component_instance('example').ctx['dataDir'], str(rt.component_data_directory('example')))
        self.assertEqual(rt.component_instance(first).ctx['dataDir'], str(rt.component_data_directory(first)))
        self.assertEqual(rt.client('example').bind(default['instanceId'],'read').instanceId,default['instanceId'])
        self.assertEqual(rt.status(first)['installationId'],default['installationId'])
        app=uuid4().hex; rt.register_application_principal(app); client=rt.application_client(app)
        rt.grant(app,first,'read'); context=rt.application_context(app)
        clone=uuid4().hex; rt.register_application_principal(clone)
        self.assert_code('permission_required',lambda:rt.application_client(clone).call(first,'read',context=rt.application_context(clone)))
        result=client.call(first,'read',context=context); self.assertEqual(result['config'],{'label':'one'}); self.assertIn(first,result['dataDir'])
        self.assert_code('permission_required',lambda:client.call(second,'read',context=context))
        old=client.bind(first,'read'); rt.stop_instance(first); rt.start_instance(first)
        self.assert_code('stale_handle',lambda:client.invoke(old,context=context))
        self.assertNotEqual(rt.status(first)['runId'],old.instance)
        for row in reversed(rt.snapshot()): rt.stop_component(row['id'],force=True,persist=False)
        self.runtime=rt=build(self.config,ROOT,state_dir=self.base/'state')
        self.assertEqual(rt.status(first)['state'],'running'); self.assertEqual(rt.status(second)['instanceId'],second)
        self.assert_code('application_identity_reserved',lambda:rt.register_application_principal(app))
        rt.register_application_principal(app, restore=True); client=rt.application_client(app); context=rt.application_context(app)
        self.assertEqual(client.call(first,'read',context=context)['instanceId'],first)
        self.assert_code('permission_required',lambda:client.call(second,'read',context=context))
    def test_application_requires_live_provider_opt_in(self):
        rt=self.runtime; app=uuid4().hex; rt.register_application_principal(app)
        component=rt.component_instance('example')
        component.operation('unscoped')(lambda p,c: 'unsafe')
        rt.grant(app,'example','unscoped'); client=rt.application_client(app); ctx=rt.application_context(app)
        self.assert_code('application_binding_unsupported',lambda:client.call('example','unscoped',context=ctx))
        component.operation('relay',applicationBinding='instance')(lambda p,c: rt.client('example').call('example','unscoped',context=c))
        rt.grant(app,'example','relay'); ctx=rt.application_context(app)
        self.assert_code('application_binding_unsupported',lambda:client.call('example','relay',context=ctx))
        component.operation('unscoped',applicationBinding='instance')(lambda p,c: 'allowed')
        self.assertEqual(client.call('example','relay',context=ctx),'allowed')
        component.operation('unscoped')(lambda p,c: 'unsafe')
        self.assert_code('application_binding_unsupported',lambda:client.call('example','relay',context=ctx))
        rt.grant('example','example','unscoped')
        self.assertEqual(rt.client('example').call('example','unscoped',context=rt.user_context('example')),'unsafe')
        component.operation('change',applicationBinding='instance')(lambda p,c: 'old')
        rt.grant(app,'example','change'); ctx=rt.application_context(app); old=client.bind('example','change')
        component.operation('change')(lambda p,c: 'new')
        self.assert_code('stale_handle',lambda:client.invoke(old,context=ctx))
        self.assert_code('application_binding_unsupported',lambda:client.call('example','change',context=ctx))

    def test_revoking_application_keeps_references_and_invalidates_sessions(self):
        rt=self.runtime; identity=rt.create_instance('example'); rt.start_instance(identity)
        app=uuid4().hex; rt.register_application_principal(app); rt.register_application_bindings(app,[identity])
        rt.grant(app,identity,'read'); old_client,old_context=rt.application_client(app),rt.application_context(app)
        rt.revoke_application_authority(app)
        self.assert_code('stale_instance',lambda:old_client.bind(identity,'read'))
        self.assert_code('invalid_context',lambda:rt.validate_context(old_context))
        self.assert_code('permission_required',lambda:rt.application_client(app).call(identity,'read',context=rt.application_context(app)))
        rt.stop_instance(identity); self.assert_code('instance_in_use',lambda:rt.destroy_instance(identity))

    def test_destroy_retains_owned_data(self):
        rt=self.runtime; identity=rt.create_instance('example'); rt.start_instance(identity)
        self.assert_code('instance_in_use',lambda:rt.destroy_instance(identity)); rt.stop_instance(identity)
        path=self.base/'state'/'component-instances'/identity; path.mkdir(parents=True); (path/'data').write_text('owned')
        rt.destroy_instance(identity); self.assertEqual((path/'data').read_text(),'owned')
        self.assert_code('not_installed',lambda:rt.status(identity))
        self.assert_code('protected_instance',lambda:rt.destroy_instance(rt.status('example')['instanceId']))
    def test_references_are_durable_and_block_destroy(self):
        rt=self.runtime; identity=rt.create_instance('example'); app=uuid4().hex
        rt.register_application_principal(app); rt.register_application_bindings(app,[identity])
        self.assert_code('instance_in_use',lambda:rt.destroy_instance(identity))
        for row in reversed(rt.snapshot()): rt.stop_component(row['id'],force=True,persist=False)
        self.runtime=rt=build(self.config,ROOT,state_dir=self.base/'state')
        self.assert_code('instance_in_use',lambda:rt.destroy_instance(identity))
        rt.register_application_principal(app); rt.unregister_application_principal(app)
        self.assertTrue(rt.destroy_instance(identity)['destroyed'])

    def test_update_keeps_instance_and_rolls_back_bad_code(self):
        rt=self.runtime; identity=rt.create_instance('example',config={'label':'saved'}); rt.start_instance(identity)
        plugin=self.base/'new'; plugin.mkdir()
        manifest=self.config['components'][-1]['manifest']; (plugin/'manifest.json').write_text(json.dumps(manifest))
        (plugin/'isolation_example.py').write_text((self.base/'plugin'/'isolation_example.py').read_text())
        self.assert_code('instance_in_use',lambda:rt.install_directory(plugin,replace=True))
        rt.stop_instance(identity); rt.install_directory(plugin,replace=True)
        self.assertEqual(rt.status(identity)['instanceId'],identity)
        rt.start_instance(identity); self.assertEqual(rt.component_instance(identity).ctx['config'],{'label':'saved'})
        rt.stop_instance(identity)
        bad=self.base/'bad'; bad.mkdir(); (bad/'manifest.json').write_text(json.dumps(manifest))
        (bad/'isolation_example.py').write_text('def create(instance_context=None): raise RuntimeError("broken")\n')
        with self.assertRaises(RuntimeError): rt.install_directory(bad,replace=True)
        self.assertEqual(rt.status('example')['state'],'running')
        rt.start_instance(identity); self.assertEqual(rt.component_instance(identity).ctx['config'],{'label':'saved'})

    def test_source_update_and_rollback_preserve_instances(self):
        from polaris_platform.sources import Sources
        rt=self.runtime; source_root=self.base/'source'; plugin=source_root/'plugin'; plugin.mkdir(parents=True)
        manifest=dict(self.config['components'][-1]['manifest'],id='source-example',name='Source example')
        (source_root/'polaris-source.json').write_text(json.dumps({'schemaVersion':1,'name':'fixture','components':[{'path':'plugin'}]}))
        (plugin/'manifest.json').write_text(json.dumps(manifest))
        (plugin/'isolation_example.py').write_text((self.base/'plugin'/'isolation_example.py').read_text())
        # Different package root avoids sharing the fixture's running module.
        manifest['entry']=dict(mode='inprocess',factory='source_multi_example:create')
        (plugin/'manifest.json').write_text(json.dumps(manifest))
        (plugin/'source_multi_example.py').write_text((plugin/'isolation_example.py').read_text())
        sources=Sources(rt,self.base/'source-state')
        rt.install(dict(id='sources',name='sources',version='1',platformApi=1,entry=dict(mode='inprocess')),lambda:sources)
        rt.start_component('sources'); control=sources.local_source_control(); source=control.add(str(source_root))
        control.install(source['id'],'source-example'); rt.start_component('source-example')
        identity=rt.create_instance('source-example',config={'label':'retained'}); rt.start_instance(identity)
        before=rt.status('source-example')['instanceId']; old_run=rt.status('source-example')['runId']
        manifest['version']='2'; (plugin/'manifest.json').write_text(json.dumps(manifest))
        control.refresh(source['id'])
        self.assert_code('instance_in_use',lambda:control.update('source-example'))
        rt.stop_instance(identity); control.update('source-example')
        self.assertEqual(rt.status('source-example')['instanceId'],before)
        self.assertNotEqual(rt.status('source-example')['runId'],old_run)
        rt.start_instance(identity); self.assertEqual(rt.component_instance(identity).ctx['config'],{'label':'retained'})
        rt.stop_instance(identity); control.rollback('source-example')
        self.assertEqual(rt.status('source-example')['manifest']['version'],'1')
        rt.start_instance(identity); self.assertEqual(rt.component_instance(identity).ctx['instanceId'],identity)
        rt.stop_instance(identity)
        manifest['version']='3'; (plugin/'manifest.json').write_text(json.dumps(manifest))
        (plugin/'source_multi_example.py').write_text('def create(instance_context=None): raise RuntimeError("bad upgrade")\n')
        control.refresh(source['id'])
        with self.assertRaisesRegex(RuntimeError,'bad upgrade'): control.update('source-example')
        self.assertEqual(rt.status('source-example')['manifest']['version'],'1')
        self.assertEqual(rt.status('source-example')['state'],'running')
        self.assertEqual(rt.status(identity)['instanceId'],identity)
        rt.start_instance(identity); self.assertEqual(rt.component_instance(identity).ctx['config'],{'label':'retained'})

    def test_removed_application_client_and_context_cannot_revive(self):
        rt=self.runtime; app=uuid4().hex; rt.register_application_principal(app)
        client,context=rt.application_client(app),rt.application_context(app)
        rt.unregister_application_principal(app); rt.register_application_principal(app)
        self.assert_code('stale_instance',lambda:client.bind('example','read'))
        self.assert_code('invalid_context',lambda:rt.validate_context(context))
if __name__=='__main__': unittest.main()
