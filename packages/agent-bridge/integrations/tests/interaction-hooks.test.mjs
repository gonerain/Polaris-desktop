import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer,createConnection} from 'node:net';
import {mkdtemp,cp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {digest} from '../codex/session.mjs';

function execute(script,env,args,input){return new Promise((resolve,reject)=>{
 const child=spawn(process.execPath,[script,...args],{env,stdio:['pipe','pipe','pipe']});
 let out='',err='';child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);
 child.on('error',reject);child.on('exit',code=>code?reject(Error(err||out||`exit ${code}`)):resolve(JSON.parse(out)));
 child.stdin.end(JSON.stringify(input));
});}
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20));}throw Error('Timed out');}

test('real PermissionRequest and remote question commands return native decisions from their waiting request',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'polaris-interaction-hook-')),plugin=join(directory,'plugin');
 await cp(fileURLToPath(new URL('../',import.meta.url)),plugin,{recursive:true});
 await writeFile(join(plugin,'codex/desktop-ipc.mjs'),`export const sendModes=['start','steer']; export async function sendDesktopMessage(){return {status:'available',state:{runs:[{turnId:'turn',status:'running'}]}};}`);
 const sockets=new Set(),frames=[];let kind='approval',notificationOnly=false;
 const bridge=createServer(socket=>{
  sockets.add(socket);socket.on('close',()=>sockets.delete(socket));let raw='';
  socket.on('data',chunk=>{raw+=chunk;let i;while((i=raw.indexOf('\n'))>=0){
   const frame=JSON.parse(raw.slice(0,i));raw=raw.slice(i+1);frames.push(frame);
   if(frame.type==='hello')socket.write('{"type":"hello","ok":true}\n');
   if(frame.type==='request'){
    let result={};
    if(frame.operation==='session.status')result={runs:[]};
    if(frame.operation==='interaction.open'){kind=frame.params.kind;result={id:'request',notificationOnly};}
    if(frame.operation==='interaction.status')result={state:'answered',answer:kind==='approval'?'deny':'Word'};
    socket.write(JSON.stringify({type:'response',requestId:frame.requestId,result})+'\n');
   }
  }});
 });
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));
 const endpoint=join(directory,'endpoint.json');
 await writeFile(endpoint,JSON.stringify({version:1,host:'127.0.0.1',port:bridge.address().port,token:'x'.repeat(40)}),{mode:0o600});
 const sid='native-request-session',hosts=join(directory,'hosts');
 const env={...process.env,POLARIS_AGENT_ENDPOINT:endpoint,POLARIS_AGENT_CODEX_DATA:hosts,CODEX_THREAD_ID:sid};
 const script=join(plugin,'codex/hook.mjs');
 try{
  await execute(script,env,[],{hook_event_name:'SessionStart',session_id:sid,cwd:directory});
  await until(()=>frames.some(f=>f.event==='session.snapshot' && f.canSend));
  const output=await execute(script,env,[],{hook_event_name:'PermissionRequest',session_id:sid,turn_id:'turn',cwd:directory,tool_name:'Bash',tool_input:{command:'pwd'}});
  assert.deepEqual(output,{hookSpecificOutput:{hookEventName:'PermissionRequest',decision:{behavior:'deny'}}});
  const question=await execute(script,env,['--ask'],{question:'Output format?',options:['PDF','Word']});
  assert.deepEqual(question,{answer:'Word'});
  const opened=frames.filter(f=>f.operation==='interaction.open');
  assert.equal(opened.length,2);assert.equal(opened[0].params.sessionId,sid);assert.equal(opened[0].params.runId,digest('turn'));
  assert.equal(frames.filter(f=>f.operation==='interaction.close').length,2);
  notificationOnly=true;
  const native=await execute(script,env,[],{hook_event_name:'PermissionRequest',session_id:sid,turn_id:'turn',cwd:directory,tool_name:'Bash',tool_input:{command:'pwd'}});
  assert.deepEqual(native,{}); // No remote decision; native Codex approval continues.
  assert.equal(frames.filter(f=>f.operation==='interaction.status').length,2);

 }finally{
  try{await execute(script,env,[],{hook_event_name:'SessionEnd',session_id:sid,cwd:directory});}catch{}
  for(const socket of sockets)socket.destroy();
  await new Promise(r=>bridge.close(r));await rm(directory,{recursive:true,force:true});
 }
});
