import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer,createConnection} from 'node:net';
import {mkdtemp,cp,appendFile,rm,writeFile,lstat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {digest} from '../codex/session.mjs';
const source=fileURLToPath(new URL('../',import.meta.url));
function run(script,env,args,input){return new Promise((resolve,reject)=>{const child=spawn(process.execPath,[script,...args],{env,stdio:['pipe','pipe','pipe']});let out='',err='';child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);child.on('error',reject);child.on('exit',code=>code?reject(Error(err||`exit ${code}`)):resolve(out));child.stdin.end(JSON.stringify(input));});}
function control(path,data){return new Promise((resolve,reject)=>{const socket=createConnection(path);let raw='';socket.on('error',reject);socket.on('connect',()=>socket.write(JSON.stringify(data)+'\n'));socket.on('data',b=>raw+=b);socket.on('end',()=>resolve(JSON.parse(raw)));});}
async function eventually(fn){for(let i=0;i<100;i++){try{if(await fn())return;}catch{}await new Promise(r=>setTimeout(r,30));}throw Error('Helper replacement did not complete');}

test('real helpers replace their build without another lifecycle hook and retain legacy helpers',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'polaris-upgrade-')),data=join(dir,'hosts'),a=join(dir,'a'),b=join(dir,'b');
 await cp(source,a,{recursive:true});await cp(source,b,{recursive:true});await appendFile(join(b,'codex','session.mjs'),'\n// build two\n');
 // Exercise the real daemon/bridge while holding its host delivery in flight.
 const hostStub=`export const sendModes=['start','steer']; export async function sendDesktopMessage(o){if(o.probeOnly)return {status:'available',state:{runs:[]}}; await new Promise(r=>setTimeout(r,500));return {status:'accepted',turnId:'once'};}`;
 await writeFile(join(a,'codex','desktop-ipc.mjs'),hostStub);await writeFile(join(b,'codex','desktop-ipc.mjs'),hostStub);
 const sockets=new Set(),frames=[];
 const bridge=createServer(socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));let raw='';socket.on('data',chunk=>{raw+=chunk;let i;while((i=raw.indexOf('\n'))>=0){const f=JSON.parse(raw.slice(0,i));raw=raw.slice(i+1);frames.push(f);if(f.type==='hello')socket.write('{"type":"hello","ok":true}\n');if(f.type==='request')socket.write(JSON.stringify({type:'response',requestId:f.requestId,result:{runs:[]}})+'\n');}});});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));const endpoint=join(dir,'endpoint.json');await writeFile(endpoint,JSON.stringify({version:1,host:'127.0.0.1',port:bridge.address().port,token:'x'.repeat(40)}),{mode:0o600});
 const env={...process.env,POLARIS_AGENT_CODEX_DATA:data,POLARIS_AGENT_ENDPOINT:endpoint,POLARIS_CODEX_IPC:join(dir,'absent.sock')};
 const sid='isolated-session',path=process.platform==='win32'?`\\\\.\\pipe\\polaris-codex-${digest(data+sid).slice(0,40)}`:join(data,`c-${digest(data+sid).slice(0,40)}.sock`);
 const upgrade=script=>run(script,env,['--upgrade-helpers'],{sessions:[{sessionId:sid,project:dir}]});
 let legacy;
 try{
  const first=JSON.parse(await upgrade(join(a,'codex','hook.mjs')));assert.equal(first.results[0].status,'not_running');
  assert.equal(JSON.parse(await run(join(a,'codex','hook.mjs'),env,['--helper-status'],{sessions:[{sessionId:sid,project:dir}]})).results[0].status,'not_running');
  await run(join(a,'codex','hook.mjs'),env,[],{hook_event_name:'SessionStart',session_id:sid,cwd:dir});
  assert.equal(JSON.parse(await run(join(b,'codex','hook.mjs'),env,['--helper-status'],{sessions:[{sessionId:sid,project:dir}]})).results[0].status,'update_available');
  await run(join(a,'codex','hook.mjs'),{...env,CODEX_THREAD_ID:sid},['--mark','Retained title'],{});
  const old=await control(path,{event:'Control',operation:'identity',sessionId:sid});
  await eventually(()=>frames.some(f=>f.event==='session.snapshot'));
  [...sockets][0].write(JSON.stringify({type:'command',command:'session.send',requestId:'inflight',sessionId:sid,mode:'start',text:'once'})+'\n');
  await eventually(async()=> (await control(path,{event:'Control',operation:'identity',sessionId:sid})).sending);
  const result=JSON.parse(await upgrade(join(b,'codex','hook.mjs')));assert.equal(result.results[0].status,'deferred');
  await eventually(async()=>{const identity=await control(path,{event:'Control',operation:'identity',sessionId:sid});return identity.build!==old.build && identity.currentVersion==='0.3.0';});
  assert.equal(JSON.parse(await upgrade(join(b,'codex','hook.mjs'))).results[0].status,'current');
  await eventually(()=>frames.filter(f=>f.event==='session.snapshot').at(-1)?.title==='Retained title');
  assert.equal(frames.filter(f=>f.event==='session.snapshot').at(-1).cwd,dir);
  assert.equal(frames.filter(f=>f.event==='command.result' && f.requestId==='inflight').length,1);
  assert.equal(frames.find(f=>f.event==='command.result').status,'accepted');
  const resultIndex=frames.findIndex(f=>f.event==='command.result'), secondHello=frames.findLastIndex(f=>f.type==='hello');
  assert.ok(resultIndex<secondHello,'old result arrives before replacement connects');
  await run(join(b,'codex','hook.mjs'),env,[],{hook_event_name:'UserPromptSubmit',session_id:sid,cwd:dir,turn_id:'stop-on-update'});
  await run(join(a,'codex','hook.mjs'),env,[],{hook_event_name:'Stop',session_id:sid,cwd:dir,turn_id:'stop-on-update',last_assistant_message:'retained stop'});
  await eventually(()=>frames.some(f=>f.event==='run.ended' && f.reply==='retained stop'));
  assert.equal(frames.filter(f=>f.event==='run.ended' && f.reply==='retained stop').length,1);
  const afterOldHook=await control(path,{event:'Control',operation:'identity',sessionId:sid});
  assert.notEqual(afterOldHook.build,old.build,'old cached lifecycle hook must never downgrade the current helper');
  const explicit=JSON.parse(await upgrade(join(a,'codex','hook.mjs')));assert.equal(explicit.results[0].status,'restarting');
  await eventually(async()=> (await control(path,{event:'Control',operation:'identity',sessionId:sid})).build===old.build);
  await control(path,{event:'SessionEnd',sessionId:sid,project:dir});
  await eventually(async()=>{try{await control(path,{event:'Control',operation:'identity',sessionId:sid});return false;}catch{return true;}});
  let calls=0;legacy=createServer(socket=>{socket.on('data',()=>{calls++;socket.end('{}\n');});});await new Promise(r=>legacy.listen(path,r));
  assert.equal(JSON.parse(await upgrade(join(b,'codex','hook.mjs'))).results[0].status,'legacy_requires_restart');assert.equal(JSON.parse(await run(join(b,'codex','hook.mjs'),env,['--helper-status'],{sessions:[{sessionId:sid,project:dir}]})).results[0].status,'legacy_requires_restart');assert.equal(calls,2);assert.equal(legacy.listening,true);
 }finally{
  if(legacy)await new Promise(r=>legacy.close(r));else try{await control(path,{event:'SessionEnd',sessionId:sid,project:dir});}catch{}
  for(const socket of sockets)socket.destroy();await new Promise(r=>bridge.close(r));await rm(dir,{recursive:true,force:true});
 }
});
