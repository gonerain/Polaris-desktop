"""Independent host processes verify persistent owner boundaries and grants."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PersistenceTests(unittest.TestCase):
    def test_host_restart_retains_installation_grants_and_component_owned_data(self):
        plugin_source = '''from pathlib import Path
import json
from polaris_platform.sdk import Component
c=Component()
store=Path(__file__).with_name('business.json')
@c.operation('set',access='write')
def set_value(value):
 store.write_text(json.dumps({'value':value}))
 return value
@c.operation('get')
def get_value(): return json.loads(store.read_text())['value']
if Path(__file__).with_name('upgrade').exists():
 @c.operation('new')
 def new(): return 'new capability'
c.run()
'''
        host_source = '''import json,sys
from pathlib import Path
from dataclasses import asdict
from polaris_platform.bootstrap import build,default_config
from polaris_platform.protocol import PlatformError,Handle
base=Path(sys.argv[1]); phase=sys.argv[2]
r=build(default_config(),state_dir=base/'state')
try:
 if phase=='first':
  r.install_directory(base/'plugin'); r.start_component('persistent')
  for op in ('set','get'): r.grant('runtime','persistent',op)
 client=r.client('runtime'); context=r.user_context('runtime')
 if phase=='first': client.call('persistent','set',{'value':'private-persisted'},context=context)
 value=client.call('persistent','get',context=context)
 result={'value':value,'status':r.status('persistent'),'handle':asdict(client.bind('persistent','get'))}
 if phase=='second':
  try: client.call('persistent','new',context=context)
  except PlatformError as error: result['new_error']=error.code
  old=json.loads((base/'previous.json').read_text())['handle']
  try: client.invoke(Handle(old['target'],old['instance'],old['operation'],tuple(old['semantic'])),context=context)
  except PlatformError as error: result['old_error']=error.code
 print(json.dumps(result))
finally:
 for row in reversed(r.snapshot()):
  if row['state']=='running': r.stop_component(row['id'],persist=False)
'''
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin = base / 'plugin'
            plugin.mkdir()
            (plugin / 'main.py').write_text(plugin_source)
            (plugin / 'manifest.json').write_text(json.dumps(dict(id='persistent', name='Persistent', version='1', platformApi=1,
                          entry=dict(mode='process', command=['{python}', 'main.py']))))
            host = base / 'host.py'
            host.write_text(host_source)
            environment = os.environ.copy()
            environment['PYTHONPATH'] = str(ROOT)
            def run(phase):
                completed = subprocess.run([sys.executable, str(host), str(base), phase], cwd=base,
                                           env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)
            first = run('first')
            (base / 'previous.json').write_text(json.dumps(first))
            (plugin / 'upgrade').touch()
            second = run('second')
            self.assertEqual(second['value'], 'private-persisted')
            self.assertEqual(second['status']['installation'], first['status']['installation'])
            self.assertNotEqual(second['status']['instance'], first['status']['instance'])
            self.assertEqual(second['new_error'], 'permission_required')
            self.assertEqual(second['old_error'], 'stale_handle')
            self.assertIn('new', second['status']['description']['operations'])
            self.assertNotIn('private-persisted', (base / 'state' / 'installations.json').read_text())
            self.assertNotIn('private-persisted', (base / 'state' / 'authorization.json').read_text())
            self.assertEqual(json.loads((plugin / 'business.json').read_text()), {'value': 'private-persisted'})
            # Simulate a fresh installation under the same public requester ID;
            # the previous authorization record must not identify this new owner.
            installations_path = base / 'state' / 'installations.json'
            installations = json.loads(installations_path.read_text())
            for installation in installations:
                if installation['manifest']['id'] == 'runtime':
                    installation['installationId'] = 'fresh-requester-installation'
            installations_path.write_text(json.dumps(installations))
            fresh_source = """import json,sys
from pathlib import Path
from polaris_platform.bootstrap import build,default_config
from polaris_platform.protocol import PlatformError
r=build(default_config(),state_dir=Path(sys.argv[1])/'state')
try:
 try: r.client('runtime').call('persistent','get',context=r.user_context('runtime'))
 except PlatformError as error: print(json.dumps({'code':error.code}))
 else: print(json.dumps({'code':'unexpected_allow'}))
finally:
 for row in reversed(r.snapshot()):
  if row['state']=='running': r.stop_component(row['id'],persist=False)
"""
            completed = subprocess.run([sys.executable, '-c', fresh_source, str(base)], cwd=base,
                                       env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)['code'], 'permission_required')

    def test_revoked_initial_config_grant_stays_revoked_after_host_restart(self):
        script = """import json,sys
from polaris_platform.bootstrap import build,default_config
from polaris_platform.protocol import PlatformError
config=default_config()
config['grants']=[{'requester':'runtime','target':'runtime','name':'list'}]
r=build(config,state_dir=sys.argv[1])
try:
 if sys.argv[2]=='first':
  assert r.client('runtime').call('runtime','list',context=r.user_context('runtime'))
  r.revoke('runtime','runtime','list')
 try: r.client('runtime').call('runtime','list',context=r.user_context('runtime'))
 except PlatformError as error: print(json.dumps({'code':error.code}))
 else: print(json.dumps({'code':'unexpected_allow'}))
finally:
 for row in reversed(r.snapshot()):
  if row['state']=='running': r.stop_component(row['id'],persist=False)
"""
        with tempfile.TemporaryDirectory() as directory:
            for phase in ('first', 'second'):
                result = subprocess.run([sys.executable, '-c', script, directory, phase], cwd=ROOT,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['code'], 'permission_required')

    def test_cli_explicit_state_directory_preserves_foundation_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            def run():
                completed = subprocess.run([sys.executable, '-m', 'polaris_platform', '--state-dir', directory],
                                           cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return {row['id']: row for row in json.loads(completed.stdout)}
            first, second = run(), run()
            for identity in first:
                self.assertEqual(first[identity]['installation'], second[identity]['installation'])
                self.assertNotEqual(first[identity]['instance'], second[identity]['instance'])
