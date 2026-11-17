import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { mkdtemp, chmod, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { sendDesktopMessage, sendModes, selectRunState } from '../codex/desktop-ipc.mjs';
import { Session, digest } from '../codex/session.mjs';

test('owner probe distinguishes offline, protocol failure, and transport failure', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'polaris-owner-'));
    const path = process.platform === 'win32' ? `\\\\.\\pipe\\polaris-test-${randomUUID()}` : join(dir, 'ipc.sock');
    const methods = [];
    const server = createServer(socket => {
        let buffer = Buffer.alloc(0);
        socket.on('error', () => {});
        socket.on('data', chunk => {
            buffer = Buffer.concat([buffer, chunk]);
            while (buffer.length >= 4 && buffer.length >= 4 + buffer.readUInt32LE(0)) {
                const size = buffer.readUInt32LE(0), frame = JSON.parse(buffer.subarray(4, size + 4));
                buffer = buffer.subarray(size + 4);
                methods.push(frame.method);
                const response = {type:'response', requestId:frame.requestId, resultType:'success', result:{clientId:'probe'}};
                if (frame.method === 'thread-owner-discovery') {
                    if (frame.params.conversationId === 'disconnect') { socket.destroy(); return; }
                    response.resultType = 'error';
                    response.error = frame.params.conversationId === 'offline' ? 'no-client-found' : 'request-version-mismatch';
                }
                const body = Buffer.from(JSON.stringify(response)), header = Buffer.alloc(4);
                header.writeUInt32LE(body.length);
                // Split a frame to exercise incremental decoding.
                socket.write(header.subarray(0, 2));
                socket.write(Buffer.concat([header.subarray(2), body]));
            }
        });
    });
    await new Promise(resolve => server.listen(path, resolve));
    if (process.platform !== 'win32') await chmod(path, 0o600);
    try {
        for (const [sessionId, error] of [['offline','owner_unavailable'], ['protocol','owner_probe_unknown'], ['disconnect','transport']]) {
            assert.deepEqual(await sendDesktopMessage({sessionId, socketPath:path, probeOnly:true}), {status:'failed', error});
        }
        assert.deepEqual(methods, Array(3).fill(['initialize','thread-owner-discovery']).flat());
    } finally {
        await new Promise(resolve => server.close(resolve));
        await rm(dir, {recursive:true, force:true});
    }
    assert.equal((await sendDesktopMessage({sessionId:'offline',socketPath:path,probeOnly:true})).error, 'transport');
});

test('owner states recover automatically without confusing liveness with send support', () => {
    const events = [], client = {event:(name, data) => events.push({name,...data})};
    const session = new Session(client, {sessionId:'one', project:'/project'});
    session.sendModes = [];
    session.ownerResult({status:'available'});
    assert.equal(events.at(-1).liveness, 'host');
    assert.equal(events.at(-1).canSend, false);
    session.runId = 'active';
    session.ownerResult({status:'failed',error:'owner_unavailable'});
    assert.deepEqual(events.at(-1), {name:'session.removed',sessionId:'one'});
    session.currentSnapshot();
    assert.equal(events.at(-1).name, 'session.removed');
    session.ownerResult({status:'failed',error:'timeout'});
    assert.equal(events.at(-2).liveness, 'unverified');
    assert.equal(events.at(-2).canSend, false);
    session.sendModes = ['start','steer'];
    session.ownerResult({status:'available'});
    assert.equal(events.at(-2).liveness, 'host');
    assert.equal(events.at(-2).canSend, true);
    assert.equal(events.at(-1).runId, 'active');
});

test('desktop sends exact start and steer payloads only to the discovered owner', async t => {
    if (!sendModes.length) return t.skip('Desktop sending not supported on this OS');
    const dir = await mkdtemp(join(tmpdir(), 'polaris-send-'));
    const path = process.platform === 'win32' ? `\\\\.\\pipe\\polaris-test-${randomUUID()}` : join(dir, 'ipc.sock');
    const requests = [];
    let answer = 'accepted', busy = false;
    const server = createServer(socket => {
        let buffer = Buffer.alloc(0);
        socket.on('error', () => {});
        socket.on('data', chunk => {
            buffer = Buffer.concat([buffer, chunk]);
            while (buffer.length >= 4 && buffer.length >= 4 + buffer.readUInt32LE(0)) {
                const size = buffer.readUInt32LE(0), frame = JSON.parse(buffer.subarray(4, size + 4));
                buffer = buffer.subarray(size + 4);
                requests.push(frame);
                if (frame.type === 'broadcast') {
                    if (!frame.params.following) continue;
                    const data = Buffer.from(JSON.stringify({type:'broadcast',sourceClientId:'exact-owner',
                        method:'thread-stream-state-changed',version:11,
                        params:{hostId:'local',conversationId:'exact-session',change:{type:'snapshot',
                            conversationState:{turns:[{turnId:'last',status:busy?'inProgress':'completed'}]}}}}));
                    const header = Buffer.alloc(4); header.writeUInt32LE(data.length);
                    socket.write(Buffer.concat([header,data]));
                    continue;
                }
                const response = {type:'response', requestId:frame.requestId, resultType:'success', result:{clientId:'probe'}};
                if (frame.method === 'thread-owner-discovery') response.handledByClientId = 'exact-owner';
                if (frame.method.startsWith('thread-follower-')) {
                    if (answer === 'disconnect') {socket.destroy();return;}
                    if (answer === 'rejected') {response.resultType='error';response.error='request-version-mismatch';}
                    else response.result = {result:frame.method.endsWith('start-turn') ? {turn:{id:'started'}} : {turnId:'steered'}};
                }
                const body = Buffer.from(JSON.stringify(response)), header = Buffer.alloc(4);
                header.writeUInt32LE(body.length);
                socket.write(Buffer.concat([header,body]));
            }
        });
    });
    await new Promise(resolve => server.listen(path, resolve));
    if (process.platform !== 'win32') await chmod(path, 0o600);
    try {
        for (const [mode, turnId, version] of [['start','started',2],['steer','steered',1]]) {
            busy = mode === 'steer';
            assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'中文 /literal',mode,project:dir,socketPath:path,readState:true}), {status:'accepted',turnId});
            const frame = requests.at(-1);
            assert.equal(frame.targetClientId, 'exact-owner');
            assert.equal(frame.params.conversationId, 'exact-session');
            assert.equal(frame.version, version);
            const input = mode === 'start' ? frame.params.turnStart.request.input : frame.params.input;
            assert.equal(input[0].text, '中文 /literal');
            if (mode === 'start') assert.equal(frame.params.turnStart.context.inheritThreadSettings,true);
        }
        assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'x',mode:'start',socketPath:path,readState:true}), {status:'failed',error:'session_busy'});
        busy = false;
        assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'x',mode:'steer',socketPath:path,readState:true}), {status:'failed',error:'session_idle'});
        const skillPath=join(dir,'remote-interaction/SKILL.md');
        assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'question',mode:'start',socketPath:path,remoteSkillPath:skillPath}), {status:'accepted',turnId:'started'});
        assert.deepEqual(requests.at(-1).params.turnStart.request.input[1],{type:'skill',name:'remote-interaction',path:skillPath});
        answer = 'rejected';
        assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'x',mode:'start',socketPath:path}), {status:'failed',error:'unavailable'});
        answer = 'disconnect';
        assert.deepEqual(await sendDesktopMessage({sessionId:'exact-session',text:'x',mode:'start',socketPath:path}), {status:'unknown',error:'transport'});
        assert.equal(requests.filter(r => r.method.startsWith('thread-follower-')).length,5,'No retry after uncertain delivery');
    } finally {
        await new Promise(resolve => server.close(resolve));
        await rm(dir,{recursive:true,force:true});
    }
});

test('host snapshot repairs stale running records and follows the actual current turn', () => {
    const events = [], session = new Session({event:(name,data)=>events.push({name,...data})},{sessionId:'chat',project:'/project'});
    session.restoreRuns([{id:digest('old'),status:'running',reply:'captured reply'}]);
    session.runId = digest('old');
    session.hostState({busy:false,runs:[{turnId:'old',status:'completed'}]});
    assert.equal(session.runId,'');
    assert.equal(events.at(-1).status,'completed');
    assert.equal(events.at(-1).reply,'captured reply');
    session.hostState({busy:true,runs:[{turnId:'old',status:'completed'},{turnId:'new',status:'running'}]});
    assert.equal(session.runId,digest('new'));
    session.handle({event:'Stop',sessionId:'chat',project:'/project',turn:digest('old'),reply:'late'});
    assert.equal(session.runId,digest('new'));
    session.hostState({busy:false,runs:[{turnId:'new',status:'completed'}]});
    assert.equal(session.runId,'');
});

test('run state extraction handles canonical history and discards conversation content', () => {
    const state=selectRunState({turnHistory:{kind:'canonical',history:{islands:[{entries:[{value:'a'},{value:'b'}]}],entitiesByKey:{
        a:{turnId:'a',status:'completed',params:{input:'SECRET'}},b:{turnId:'b',status:'inProgress',items:['SECRET']}}}}});
    assert.deepEqual(state,{busy:true,runs:[{turnId:'a',status:'completed'},{turnId:'b',status:'running'}]});
    assert.equal(JSON.stringify(state).includes('SECRET'),false);
    assert.equal(selectRunState({turns:[{turnId:'x',status:'unexpected'}]}),null);
    assert.equal(selectRunState({}),null);
    const result=selectRunState({turns:[{turnId:'final',status:'completed',items:[
        {type:'reasoning',text:'SECRET'},{type:'agentMessage',phase:'commentary',text:'NOT FINAL'},
        {type:'agentMessage',phase:'final_answer',text:'完成正文'}]}]});
    assert.equal(result.runs[0].reply,'完成正文');
    assert.equal(JSON.stringify(result).includes('SECRET'),false);
});
