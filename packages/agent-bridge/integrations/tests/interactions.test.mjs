import test from 'node:test';
import assert from 'node:assert/strict';
import {waitForInteraction,permissionPrompt} from '../codex/interactions.mjs';

test('a native waiting request returns exactly its human answer and closes',async()=>{
 const calls=[];
 const client={ready:true,async request(operation,args){calls.push({operation,args});return operation==='interaction.open'?{id:'one'}:operation==='interaction.status'?{state:'answered',answer:'deny'}:{};}};
 const state={ownerVerified:true,runId:'run',sessionId:'native'};
 assert.deepEqual(await waitForInteraction(client,state,{kind:'approval',runId:'run',prompt:'command'}),{answer:'deny'});
 assert.deepEqual(calls.map(c=>c.operation),['interaction.open','interaction.status','interaction.close']);
 assert.equal(calls[0].args.sessionId,'native');
});
test('expired or changed requests never manufacture an approval',async()=>{
 const calls=[];const state={ownerVerified:true,runId:'run',sessionId:'native'};
 const client={ready:true,async request(op){calls.push(op);return op==='interaction.open'?{id:'one'}:{state:'expired'};}};
 await assert.rejects(waitForInteraction(client,state,{kind:'question',prompt:'Question'}));
 assert.equal(calls.at(-1),'interaction.close');
 const malformed={ready:true,async request(op){return op==='interaction.open'?{id:'one'}:{state:'answered'};}};
 await assert.rejects(waitForInteraction(malformed,state,{kind:'question',prompt:'Question'}));
 await assert.rejects(waitForInteraction(client,state,{kind:'approval',runId:'another',prompt:'Command'}));
 assert.equal(permissionPrompt({turn_id:'turn',tool_name:'Bash',tool_input:{command:'pwd'}}),'Bash\n{"command":"pwd"}');
 assert.throws(()=>permissionPrompt({turn_id:'turn',tool_name:'Bash',tool_input:{command:'x'.repeat(1401)}}));
});
