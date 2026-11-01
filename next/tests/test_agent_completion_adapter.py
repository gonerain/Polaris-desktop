"""Actual isolated components and bridge; no model or external messaging."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
import test_weixin_agent_e2e as e2e
from polaris_weixin.controller import ToolExecutor
from polaris_weixin.completion import CompletionAdapter
from polaris_platform.sdk import _LocalContext


class CompletionTests(unittest.TestCase):
    setUp = e2e.WeixinAgentEndToEndTests.setUp
    tearDown = e2e.WeixinAgentEndToEndTests.tearDown
    wait = e2e.WeixinAgentEndToEndTests.wait
    call = e2e.WeixinAgentEndToEndTests.call

    def submit(self, text='notification fixture', delivery_id=None):
        self.agent_component.mark(self.session)
        self.component.client.context = 'fake-context'
        context=_LocalContext(self.runtime.client(self.identity),self.context)
        executor=ToolExecutor(context,[{'target':e2e.TARGET,'operation':'send'}],
                              'collaboration',self.identity,self.component.completions)
        executor.execute('help',{'component':e2e.TARGET},threading.Event())
        args=dict(session_id=self.session,text=text,mode='start')
        if delivery_id:args['delivery_id']=delivery_id
        receipt=executor.execute('call',dict(component=e2e.TARGET,operation='send',arguments=args),threading.Event())
        self.wait(lambda:self.agent_component.delivery(receipt['id'])['status']=='accepted')
        return receipt

    def notices(self):
        return [m['item_list'][0]['text_item']['text'] for m in self.fake.sent]

    def test_real_bridge_completion_notifies_without_model_and_is_deduplicated(self):
        # No WeixinAgent.run call: sending and callback are entirely deterministic.
        self.component.agent.agent = None
        receipt=self.submit()
        self.wait(lambda:len(self.fake.sent)==1)
        self.assertIn('【任务结束】',self.notices()[0])
        self.assertIn('测试宿主已完成：notification fixture',self.notices()[0])
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='delivered')
        self.host.send(type='event',event='run.ended',sessionId='fixture-a62bc0',runId='fixture-run',status='completed',reply='duplicate')
        self.agent_component.completions.flush()
        self.assertEqual(len(self.fake.sent),1)
        adapter=CompletionAdapter(self.component.client,self.component.completions.path,self.identity)
        token=next(iter(adapter.records))
        result=dict(deliveryId=receipt['id'],sessionId=self.session,runId='fixture-run',status='completed',reply='duplicate')
        self.assertTrue(adapter.receive(token,result,e2e.TARGET)['duplicate'])
        self.assertEqual(len(self.fake.sent),1)

    def test_desktop_send_without_callback_never_notifies(self):
        self.agent_component.mark(self.session)
        receipt=self.agent_component.send(self.session,'desktop message','start')
        self.wait(lambda:self.agent_component.delivery(receipt['id'])['status']=='accepted')
        self.wait(lambda:self.agent_component.result(self.session) is not None)
        self.agent_component.completions.flush()
        self.assertEqual(self.fake.sent,[])

    def test_multiple_deliveries_for_same_run_notify_once(self):
        first=self.submit('first steering text')
        self.wait(lambda:len(self.fake.sent)==1)
        second=self.submit('second steering text')
        self.wait(lambda:self.agent_component.delivery(second['id']).get('completionStatus')=='delivered')
        self.assertEqual(len(self.fake.sent),1)

    def test_waiting_callback_recovers_after_disconnect(self):
        self.component.client.state='offline'
        receipt=self.submit()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='blocked')
        self.component.client.state='connected'
        self.agent_component.completions.wake.set()
        self.wait(lambda:len(self.fake.sent)==1)
        self.assertIn('已完成',self.notices()[0])

    def test_pending_completion_survives_agent_restart(self):
        self.component.client.state='offline'
        receipt=self.submit()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='blocked')
        self.runtime.stop_component(e2e.TARGET,force=True)
        self.agent_component=e2e.Agent(data_dir=Path(self.directory.name)/'agent')
        self.runtime.start_component(e2e.TARGET)
        self.component.client.state='connected'
        self.agent_component.completions.wake.set()
        self.wait(lambda:len(self.fake.sent)==1)
        self.wait(lambda:self.agent_component.delivery(receipt['id'])['completionStatus']=='delivered')

    def test_stopping_weixin_does_not_stop_agent(self):
        self.component.client.state='offline'
        receipt=self.submit()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='blocked')
        self.runtime.stop_component(self.identity,force=True)
        self.agent_component.completions.flush()
        self.assertEqual(self.runtime.status(e2e.TARGET)['state'],'running')
        self.assertTrue(self.agent_component.sessions())

    def test_uncertain_weixin_send_is_not_repeated(self):
        original=self.fake.request
        attempts=[]
        def network(origin,endpoint,body,**kwargs):
            if endpoint=='ilink/bot/sendmessage':
                attempts.append(body)
                raise TimeoutError('fixture network ambiguity')
            return original(origin,endpoint,body,**kwargs)
        self.fake.request=network
        receipt=self.submit()
        self.wait(lambda:len(attempts)==1 and not self.component.client.sending)
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='delivered')
        self.agent_component.completions.flush()
        self.assertEqual(len(attempts),1)
        self.assertIn('未知',self.component.client.messages[-1]['status'])

    def test_unknown_and_unrelated_run_do_not_notify_then_terminal_does(self):
        # Keep callback processing blocked until the test has adjusted fixture events.
        self.component.client.state='offline'
        receipt=self.submit()
        self.wait(lambda:self.agent_component.result(self.session) is not None)
        with self.agent_component.store.lock:
            delivery=self.agent_component.store.deliveries[receipt['id']]
            delivery['runId']='actual-target-run'
            self.agent_component.store.changed()
        self.agent_component.store.run_event(self.session,'actual-target-run','unknown','candidate')
        self.component.client.state='connected'
        self.agent_component.completions.flush()
        self.assertEqual(self.fake.sent,[])
        self.agent_component.store.run_event(self.session,'actual-target-run','failed','真实失败原因')
        self.wait(lambda:len(self.fake.sent)==1)
        self.assertIn('失败',self.notices()[0])
        self.assertIn('真实失败原因',self.notices()[0])

    def test_unavailable_weixin_recovers_and_changed_account_cannot_receive(self):
        self.component.client.state='offline'
        receipt=self.submit()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='blocked')
        self.assertEqual(self.fake.sent,[])
        self.component.client.state='connected'
        self.component.client.account['userId']='different-user'
        self.agent_component.completions.wake.set()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='unknown')
        self.assertEqual(self.fake.sent,[])

    def test_callback_permission_revocation_prevents_notification(self):
        self.runtime.revoke('user',self.identity,'complete_agent_run')
        receipt=self.submit()
        self.wait(lambda:self.agent_component.delivery(receipt['id']).get('completionStatus')=='blocked')
        self.assertEqual(self.fake.sent,[])
        self.runtime.grant('user',self.identity,'complete_agent_run')
        self.agent_component.completions.wake.set()
        self.wait(lambda:len(self.fake.sent)==1)

    def test_agent_import_and_start_without_weixin_package(self):
        root=Path(__file__).resolve().parents[1]
        script='''
import sys,tempfile
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'components/agent')]
from polaris_agent import Agent
from polaris_platform.runtime import Runtime
from polaris_platform.bootstrap import build,default_config
with tempfile.TemporaryDirectory() as directory:
 r=build(default_config())
 r.install(dict(id='only-agent',name='Agent',version='1',platformApi=1,entry=dict(mode='inprocess')),lambda:Agent(directory))
 r.start_component('only-agent')
 assert r.component_instance('only-agent').sessions()==[]
 assert r.component_instance('only-agent').describe()['dependencies']==[]
 assert not any(n.startswith('polaris_weixin') for n in sys.modules)
 r.stop_component('only-agent',force=True)
'''
        result=subprocess.run([sys.executable,'-I','-c',script,str(root)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
