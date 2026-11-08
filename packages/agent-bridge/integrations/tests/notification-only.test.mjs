import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForInteraction } from '../codex/interactions.mjs';

test('notification-only interaction never waits, approves, or returns a model answer', async () => {
  const calls = [];
  const client = { ready: true, request: async (method) => {
    calls.push(method);
    if (method === 'interaction.open') return {id: 'observed', notificationOnly: true};
    if (method === 'interaction.status') throw Error('must not poll');
    return {};
  }};
  for (const kind of ['question', 'approval']) {
    await assert.rejects(waitForInteraction(client, { ownerVerified: true, runId: 'run', sessionId: 'native' },
      {kind, prompt: 'Need user input'}), /native host/);
  }
  assert.deepEqual(calls, ['interaction.open', 'interaction.close', 'interaction.open', 'interaction.close']);
});
