import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, lstat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { digest } from '../codex/session.mjs';

const script = fileURLToPath(new URL('../codex/hook.mjs', import.meta.url));
function run(env, args, input) {
    return new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [script, ...args], {env, stdio:['pipe','pipe','pipe']});
        let output = '', error = '';
        child.stdout.on('data', chunk => output += chunk);
        child.stderr.on('data', chunk => error += chunk);
        child.on('error', reject);
        child.on('exit', code => code === 0 ? resolve(JSON.parse(output)) : reject(Error(error)));
        child.stdin.end(JSON.stringify(input));
    });
}

test('stale Unix helper socket recovers and concurrent hooks preserve the live helper',
    {skip:process.platform === 'win32', timeout:20000}, async () => {
    const root = await mkdtemp(join(tmpdir(), 'polaris-stale-helper-'));
    const sid = 'diagnostic-stale-session';
    const path = join(root, `c-${digest(root + sid).slice(0, 40)}.sock`);
    const env = {...process.env, POLARIS_AGENT_CODEX_DATA:root,
        POLARIS_AGENT_ENDPOINT:join(root, 'missing-endpoint.json'),
        POLARIS_CODEX_IPC:join(root, 'missing-desktop.sock')};
    const event = hook_event_name => ({hook_event_name, session_id:sid, cwd:root});
    const status = () => run(env, ['--helper-status'], {sessions:[{sessionId:sid, project:root}]});
    // A killed listener leaves exactly the socket left behind by a host crash.
    const stale = spawn(process.execPath, ['--input-type=module', '-e',
        "import {createServer} from 'node:net'; createServer().listen(process.argv[1],()=>console.log('ready'));", path]);
    await once(stale.stdout, 'data');
    stale.kill('SIGKILL');
    await once(stale, 'exit');
    try {
        assert.equal((await status()).results[0].status, 'not_running');
        await Promise.all(Array.from({length:8}, () => run(env, [], event('SessionStart'))));
        assert.equal((await status()).results[0].status, 'current');
        const live = await lstat(path);
        await Promise.all(Array.from({length:8}, () => run(env, [], event('SessionStart'))));
        assert.equal((await status()).results[0].status, 'current');
        assert.equal((await lstat(path)).ino, live.ino, 'live helper socket must not be replaced');
    } finally {
        await run(env, [], event('SessionEnd'));
        await rm(root, {recursive:true, force:true});
    }
});
