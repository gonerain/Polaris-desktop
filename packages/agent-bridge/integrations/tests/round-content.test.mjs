import test from 'node:test';
import assert from 'node:assert/strict';
import { metadata, Session, digest } from '../codex/session.mjs';
import { selectRunState } from '../codex/desktop-ipc.mjs';
import { waitForInteraction } from '../codex/interactions.mjs';

test('current-turn prompt and final response survive Stop and host completion without mixing turns', () => {
  const events=[]; const session=new Session({event:(event,data)=>events.push({event,...data})},{sessionId:'s',project:'/p'});
  session.handle({...metadata({hook_event_name:'UserPromptSubmit',session_id:'s',turn_id:'one',prompt:'QUESTION ONE'}),project:'/p'});
  session.handle({event:'Stop',sessionId:'s',project:'/p',turn:digest('one'),reply:'ANSWER ONE'});
  session.hostState({runs:[{turnId:'one',status:'completed',prompt:'QUESTION ONE',reply:'ANSWER ONE'}]});
  session.handle({...metadata({hook_event_name:'UserPromptSubmit',session_id:'s',turn_id:'two',prompt:'QUESTION TWO'}),project:'/p'});
  session.hostState({runs:[{turnId:'one',status:'completed',prompt:'QUESTION ONE',reply:'ANSWER ONE'},
    {turnId:'two',status:'completed',prompt:'QUESTION TWO',reply:'ANSWER TWO'}]});
  const endings=events.filter(e=>e.event==='run.ended' && e.status==='completed');
  assert.equal(endings[0].prompt,'QUESTION ONE'); assert.equal(endings[0].reply,'ANSWER ONE');
  assert.equal(endings[1].prompt,'QUESTION TWO'); assert.equal(endings[1].reply,'ANSWER TWO');
  const bounded=metadata({hook_event_name:'UserPromptSubmit',session_id:'s',turn_id:'three',prompt:'字'.repeat(5000)});
  assert.equal(bounded.prompt.length,4000); assert.equal(bounded.promptTruncated,true);
});

test('host extraction selects only same-turn text input, final answer, and native review mode', () => {
  const state=selectRunState({turns:[{turnId:'t',status:'completed',params:{approvalsReviewer:'auto_review',input:[
    {type:'text',text:'USER QUESTION'},{type:'image',path:'IMAGE SECRET'}],additionalContext:'CONTEXT SECRET'},items:[
    {type:'reasoning',text:'REASONING SECRET'},{type:'commandExecution',aggregatedOutput:'TOOL SECRET'},
    {type:'agentMessage',phase:'commentary',text:'COMMENT SECRET'},
    {type:'agentMessage',phase:'final_answer',text:'FINAL ANSWER'}]}]});
  assert.equal(state.runs[0].prompt,'USER QUESTION'); assert.equal(state.runs[0].reply,'FINAL ANSWER');
  assert.equal(state.runs[0].approvalReviewer,'auto_review'); assert.equal(JSON.stringify(state).includes('SECRET'),false);
});

test('automatic review does not open a user interaction or issue a hook decision', async () => {
  let refreshed=false,requests=0;
  const state={ownerVerified:true,runId:'run',knownRuns:new Map(),refreshApprovalState:async()=>{
    refreshed=true; state.knownRuns.set('run',{approvalReviewer:'auto_review'});
  }};
  const result=await waitForInteraction({ready:true,request:async()=>{requests++;throw Error('must not request');}},state,
    {kind:'approval',runId:'run',prompt:'Auto reviewed command'});
  assert.equal(refreshed,true); assert.equal(requests,0); assert.deepEqual(result,{automatic:true});
  assert.equal('answer' in result,false);
});

test('a user question is still notified even in an auto-review turn', async () => {
  let opened=false;
  const state={ownerVerified:true,runId:'run',knownRuns:new Map([['run',{approvalReviewer:'auto_review'}]])};
  await assert.rejects(waitForInteraction({ready:true,request:async(method)=>{
    if(method==='interaction.open'){opened=true;return {id:'q',notificationOnly:true};}return {};
  }},state,{kind:'question',prompt:'Need a human answer'}),/native host/);
  assert.equal(opened,true);
});
