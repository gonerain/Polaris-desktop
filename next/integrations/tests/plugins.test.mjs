import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter, once } from 'node:events';
import { createServer } from 'node:net';
import { mkdtemp,writeFile,rm,chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BridgeClient } from '../client.mjs';
import { install } from '../pi/runtime.mjs';
import { Session,metadata } from '../codex/session.mjs';
import { sendDesktopMessage } from '../codex/desktop-ipc.mjs';
class Fake extends EventEmitter {static all=[];constructor(){super();this.events=[];this.ready=true;Fake.all.push(this);}start(){this.emit('connected');}stop(){this.stopped=true;}event(name,data){this.events.push({name,...data});}request(operation,params){this.operation={operation,params};return Promise.resolve({marked:true});}}
function harness(){const handlers={},commands={},tools={},sent=[];const pi={on:(n,f)=>handlers[n]=f,registerCommand:(n,c)=>commands[n]=c,registerTool:t=>tools[t.name]=t,sendUserMessage:(...a)=>sent.push(a)};install(pi,{},Fake);let sid='first';const ctx={cwd:'/project',isIdle:()=>true,sessionManager:{getSessionId:()=>sid,getSessionName:()=>''},ui:{notify(){}}};return {handlers,commands,tools,sent,ctx,setSid:s=>sid=s};}
test('Pi settlement reports last assistant text once and reconnect only snapshots',async()=>{const h=harness();h.handlers.session_start({},h.ctx);const c=Fake.all.at(-1);h.handlers.agent_start();h.handlers.message_end({message:{role:'assistant',stopReason:'stop',content:[{type:'text',text:'Final reply'}]}});h.handlers.agent_settled({aborted:false});h.handlers.agent_settled({aborted:false});assert.equal(c.events.filter(e=>e.name==='run.ended').length,1);assert.equal(c.events.find(e=>e.name==='run.ended').reply,'Final reply');assert.equal(c.events.find(e=>e.name==='run.ended').status,'completed');c.emit('connected');assert.equal(c.events.at(-1).name,'session.snapshot');await h.tools.mark_current.execute('',{name:'Chosen'});assert.equal(c.operation.operation,'session.mark');h.handlers.session_shutdown();assert.equal(c.stopped,true);});
test('Pi sends only to still bound session and does not expand templates',()=>{const h=harness();h.handlers.session_start({},h.ctx);const c=Fake.all.at(-1);c.emit('command',{command:'session.send',requestId:'a',mode:'start',sessionId:'first',text:'/literal'});assert.equal(h.sent.length,1);assert.equal(h.sent[0][1].expandPromptTemplates,false);h.setSid('second');c.emit('command',{command:'session.send',requestId:'b',mode:'start',sessionId:'first',text:'wrong'});assert.equal(h.sent.length,1);assert.equal(c.events.at(-1).status,'rejected');});
test('Codex Stop remains unknown, is deduplicated, and selects bounded reply only',()=>{const c=new Fake(),s=new Session(c,{sessionId:'one',project:'/project'});s.handle({event:'UserPromptSubmit',sessionId:'one',project:'/project',turn:'t'});const stop={event:'Stop',sessionId:'one',project:'/project',turn:'t',reply:'done'};s.handle(stop);s.handle(stop);assert.equal(c.events.filter(x=>x.name==='run.ended').length,1);assert.equal(c.events.find(x=>x.name==='run.ended').status,'unknown');const m=metadata({hook_event_name:'Stop',session_id:'one',last_assistant_message:'x'.repeat(9000),prompt:'SECRET'});assert.equal(m.reply.length,8000);assert.equal(JSON.stringify(m).includes('SECRET'),false);});
test('private endpoint NDJSON authenticates, responds and handles send command',async()=>{const dir=await mkdtemp(join(tmpdir(),'agent-plugin-'));const server=createServer(socket=>{let b='';socket.on('data',chunk=>{b+=chunk;let i;while((i=b.indexOf('\n'))>=0){const f=JSON.parse(b.slice(0,i));b=b.slice(i+1);if(f.type==='hello'){assert.equal(f.adapter,'pi');socket.write(JSON.stringify({type:'hello',ok:true})+'\n');}else if(f.type==='request')socket.write(JSON.stringify({type:'response',requestId:f.requestId,result:{marked:true}})+'\n');}});});await new Promise(r=>server.listen(0,'127.0.0.1',r));const path=join(dir,'endpoint.json');await writeFile(path,JSON.stringify({version:1,host:'127.0.0.1',port:server.address().port,token:'a'.repeat(40)}),{mode:0o600});const c=new BridgeClient({adapter:'pi',clientId:'one',endpoint:path});try{const ready=once(c,'connected');c.start();await ready;assert.deepEqual(await c.request('session.mark',{sessionId:'one'}),{marked:true});}finally{c.stop();await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}});
test('Codex owner-only probe never dispatches a user message',async()=>{const dir=await mkdtemp(join(tmpdir(),'agent-ipc-')),path=process.platform==='win32'?`\\\\.\\pipe\\polaris-test-${Date.now()}-${process.pid}`:join(dir,'ipc.sock'),methods=[];const server=createServer(socket=>{let b=Buffer.alloc(0);socket.on('data',chunk=>{b=Buffer.concat([b,chunk]);while(b.length>=4 && b.length>=4+b.readUInt32LE(0)){const n=b.readUInt32LE(0),f=JSON.parse(b.subarray(4,n+4));b=b.subarray(n+4);methods.push(f.method);const response={type:'response',requestId:f.requestId,resultType:'success',result:{clientId:'fake'},handledByClientId:'owner'};const data=Buffer.from(JSON.stringify(response)),header=Buffer.alloc(4);header.writeUInt32LE(data.length);socket.write(Buffer.concat([header,data]));}});});await new Promise(r=>server.listen(path,r));if(process.platform!=='win32')await chmod(path,0o600);try{assert.equal((await sendDesktopMessage({sessionId:'one',socketPath:path,probeOnly:true})).status,'available');assert.deepEqual(methods,['initialize','thread-owner-discovery']);}finally{await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}});
test('Codex explicit mark command uses exact thread identity through persistent helper',async()=>{
 const {execFile,spawn}=await import('node:child_process');const {promisify}=await import('node:util');
 const dir=await mkdtemp(join(tmpdir(),'agent-hook-')),endpoint=join(dir,'endpoint.json'),events=[];const sockets=new Set();
 const server=createServer(socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));let b='';socket.on('data',chunk=>{b+=chunk;let i;while((i=b.indexOf('\n'))>=0){const f=JSON.parse(b.slice(0,i));b=b.slice(i+1);if(f.type==='hello')socket.write('{"type":"hello","ok":true}\n');else if(f.type==='event')events.push(f);else if(f.type==='request')socket.write(JSON.stringify({type:'response',requestId:f.requestId,result:{marked:true,sessionId:f.params.sessionId}})+'\n');}});});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));await writeFile(endpoint,JSON.stringify({version:1,host:'127.0.0.1',port:server.address().port,token:'a'.repeat(40)}),{mode:0o600});
 const script=fileURLToPath(new URL('../codex/hook.mjs',import.meta.url)),env={...process.env,POLARIS_AGENT_CODEX_DATA:dir,CODEX_HOME:dir,POLARIS_CODEX_IPC:process.platform==='win32'?`\\\\.\\pipe\\polaris-missing-${process.pid}-${Date.now()}`:join(dir,'missing.sock'),POLARIS_AGENT_ENDPOINT:endpoint,CODEX_THREAD_ID:'fake-exact-thread'};
 try {const output=await promisify(execFile)(process.execPath,[script,'--mark','Chosen chat'],{env,timeout:8000});assert.match(output.stderr,/marked/);assert.equal(events.find(e=>e.event==='session.snapshot').sessionId,'fake-exact-thread');assert.equal(events.filter(e=>e.event==='session.snapshot').at(-1).title,'Chosen chat');}
 finally {const child=spawn(process.execPath,[script],{env,stdio:['pipe','pipe','pipe']});child.stdin.end(JSON.stringify({hook_event_name:'SessionEnd',session_id:'fake-exact-thread',cwd:dir}));await once(child,'exit');for(const socket of sockets)socket.destroy();await new Promise(r=>server.close(r));await rm(dir,{recursive:true,force:true});}
});

test('Pi requires explicit matching mode and keeps aliases across snapshots', async () => {
 const h=harness();h.handlers.session_start({},h.ctx);const c=Fake.all.at(-1);
 c.emit('command',{command:'session.send',requestId:'missing',sessionId:'first',text:'x'});
 assert.equal(c.events.at(-1).detail,'unsupported_mode');
 c.emit('command',{command:'session.send',requestId:'idle-steer',mode:'steer',sessionId:'first',text:'x'});
 assert.equal(c.events.at(-1).detail,'session_idle');
 h.ctx.isIdle=()=>false;
 c.emit('command',{command:'session.send',requestId:'busy-start',mode:'start',sessionId:'first',text:'x'});
 assert.equal(c.events.at(-1).detail,'session_busy');assert.equal(h.sent.length,0);
 await h.tools.mark_current.execute('',{name:'Alias'});h.handlers.session_info_changed();
 assert.equal(c.events.at(-1).title,'Alias');
 h.handlers.agent_start();c.emit('connected');assert.equal(c.events.at(-1).name,'run.started');
 assert.doesNotThrow(()=>h.handlers.message_end({message:{role:'assistant',content:null}}));
 h.handlers.session_shutdown();
});
test('Codex reconnect republishes active run and unverified liveness',()=>{
 const c=new Fake(),s=new Session(c,{sessionId:'one',project:'/project'});
 s.handle({event:'UserPromptSubmit',sessionId:'one',project:'/project',turn:'t'});
 s.currentSnapshot();assert.equal(c.events.at(-1).name,'run.started');
 assert.equal(c.events.at(-2).liveness,'unverified');assert.equal(c.events.at(-2).canSend,false);
 s.ownerVerified=true;s.currentSnapshot();assert.equal(c.events.at(-2).liveness,'host');
});

test('Codex later Stop updates a candidate reply and ignores older turns after a new turn',()=>{
 const c=new Fake(),s=new Session(c,{sessionId:'one',project:'/project'});
 const event=(name,turn,reply)=>s.handle({event:name,sessionId:'one',project:'/project',turn,reply});
 event('UserPromptSubmit','first');event('Stop','first','candidate');event('Stop','first','candidate');
 event('Stop','first','newer reply');
 const endings=()=>c.events.filter(e=>e.name==='run.ended');
 assert.equal(endings().length,2);assert.equal(endings().at(-1).reply,'newer reply');
 event('UserPromptSubmit','second');event('Stop','first','late obsolete reply');
 assert.equal(endings().length,2);event('Stop','second','second reply');
 assert.equal(endings().length,3);assert.equal(endings().at(-1).reply,'second reply');
});
test('Pi reports reply truncation explicitly',()=>{
 const h=harness();h.handlers.session_start({},h.ctx);const c=Fake.all.at(-1);h.handlers.agent_start();
 h.handlers.message_end({message:{role:'assistant',stopReason:'stop',content:[{type:'text',text:'x'.repeat(128001)}]}});
 h.handlers.agent_settled({aborted:false});const ending=c.events.find(e=>e.name==='run.ended');
 assert.equal(ending.reply.length,128000);assert.equal(ending.replyTruncated,true);h.handlers.session_shutdown();
});
