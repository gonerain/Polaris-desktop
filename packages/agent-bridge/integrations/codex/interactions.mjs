// A waiting hook keeps ownership of the native request; the bridge only returns a human answer.
import { setTimeout as pause } from 'node:timers/promises';

export async function waitForInteraction(client, state, data, signal) {
    if (!client.ready || !state.ownerVerified || !state.runId ||
        (data.runId && data.runId !== state.runId)) throw Error('No verified active session');
    if (!['approval','question'].includes(data.kind) || typeof data.prompt !== 'string' ||
        !data.prompt.trim() || data.prompt.length > 1400) throw Error('Unsupported interaction');
    const boundRun=state.runId;
    const opened = await client.request('interaction.open', {
        sessionId:state.sessionId, runId:state.runId, kind:data.kind, prompt:data.prompt,
        options:data.options || [], timeout:110,
    });
    const deadline = Date.now()+110000;
    try {
        while (Date.now()<deadline && !signal?.aborted) {
            if (state.runId!==boundRun || !state.ownerVerified) throw Error('Session changed');
            const result=await client.request('interaction.status',{sessionId:state.sessionId,id:opened.id});
            if (result.state==='answered') {
                if (typeof result.answer!=='string' || !result.answer || result.answer.length>8000 ||
                    (data.kind==='approval' && !['allow','deny'].includes(result.answer)))
                    throw Error('Invalid human answer');
                return {answer:result.answer};
            }
            if (result.state!=='pending') throw Error('Interaction expired');
            await pause(250,undefined,{signal});
        }
        throw Error('Interaction expired');
    } finally {
        try { await client.request('interaction.close',{sessionId:state.sessionId,id:opened.id}); } catch { /* Disconnect expires pending requests. */ }
    }
}

export function permissionPrompt(input) {
    if (typeof input?.tool_name!=='string' || !input.tool_name || typeof input.turn_id!=='string' || !input.turn_id)
        throw Error('Unsupported permission request');
    const body=JSON.stringify(input.tool_input ?? {});
    const prompt=`${input.tool_name}\n${body}`;
    // Never ask the user to approve a truncated operation preview.
    if (prompt.length>1400) throw Error('Permission preview too long; use the desktop');
    return prompt;
}
