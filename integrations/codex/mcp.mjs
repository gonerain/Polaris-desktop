// Dependency-free MCP stdio adapter. Lifecycle reporting is independent of model tools.
import { BridgeClient } from '../client.mjs';

const tools = [
    { name: 'polaris_components', description: 'Discover local Polaris components without reading business data.',
        inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
    { name: 'polaris_help', description: 'Read component operations, arguments and permissions before calling it. Does not grant access.',
        inputSchema: { type: 'object', properties: { component: { type: 'string' } }, required: ['component'], additionalProperties: false } },
    { name: 'polaris_call', description: 'Call an operation after reading help. User must authorize the component in Polaris. After timeout/disconnect or applied=true, query actual state before retrying a write.',
        inputSchema: { type: 'object', properties: { component: { type: 'string' }, operation: { type: 'string' },
            args: { type: 'object', additionalProperties: true } }, required: ['component', 'operation'], additionalProperties: false } },
];
let relay;
try { if (process.env.POLARIS_RELAY) relay = JSON.parse(process.env.POLARIS_RELAY); }
catch { process.stderr.write('Invalid POLARIS_RELAY: expected JSON argv array\n'); process.exit(1); }
const client = new BridgeClient({ name: 'Codex tools', relay });
client.start();
const send = message => {
    const line = JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n';
    if (process.stdout.writableLength > 131072) return shutdown();
    process.stdout.write(line);
};
function shutdown() { client.stop(); process.stdin.destroy(); }
process.stdin.on('end', shutdown);
process.on('SIGTERM', () => { shutdown(); process.exit(0); });
process.on('SIGINT', () => { shutdown(); process.exit(0); });
let active = 0;
async function dispatch(message) {
    if (!message || message.jsonrpc !== '2.0' || typeof message.method !== 'string') {
        send({ id: message?.id ?? null, error: { code: -32600, message: 'Invalid request' } });
        return;
    }
    if (!Object.hasOwn(message, 'id')) return;
    const { id, method, params = {} } = message;
    if (active >= 32) return send({ id, error: { code: -32000, message: 'Too many requests' } });
    active++;
    try {
        let result;
        if (method === 'initialize') result = {
            protocolVersion: ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'].includes(params.protocolVersion)
                ? params.protocolVersion : '2025-11-25',
            capabilities: { tools: {} }, serverInfo: { name: 'polaris', version: '0.1.0' },
        };
        else if (method === 'ping') result = {};
        else if (method === 'tools/list') result = { tools };
        else if (method === 'tools/call') {
            const index = tools.findIndex(tool => tool.name === params.name);
            if (index < 0) { send({ id, error: { code: -32602, message: 'Unknown tool' } }); return; }
            const args = params.arguments ?? {};
            const schema = tools[index].inputSchema;
            if (!args || typeof args !== 'object' || Array.isArray(args) ||
                Object.keys(args).some(key => !Object.hasOwn(schema.properties, key)) ||
                (schema.required || []).some(key => typeof args[key] !== 'string' || !args[key].trim()) ||
                (Object.hasOwn(args, 'args') && (!args.args || typeof args.args !== 'object' || Array.isArray(args.args)))) {
                send({ id, error: { code: -32602, message: 'Invalid tool arguments' } }); return;
            }
            try {
                const value = await client.request(['components.list', 'components.help', 'components.call'][index], args);
                result = { content: [{ type: 'text', text: JSON.stringify(value) }] };
            } catch (error) {
                result = { isError: true, content: [{ type: 'text', text: error.message }] };
            }
        } else { send({ id, error: { code: -32601, message: 'Method not found' } }); return; }
        send({ id, result });
    } catch { send({ id, error: { code: -32603, message: 'Request failed' } }); }
    finally { active--; }
}
let buffer = Buffer.alloc(0);
process.stdin.on('data', chunk => {
    buffer = Buffer.concat([buffer, chunk]);
    let index;
    while ((index = buffer.indexOf(10)) >= 0) {
        if (index + 1 > 65536) return shutdown();
        const line = buffer.subarray(0, index).toString('utf8');
        buffer = buffer.subarray(index + 1);
        try { void dispatch(JSON.parse(line)); }
        catch { send({ id: null, error: { code: -32700, message: 'Parse error' } }); }
    }
    if (buffer.length > 65536) shutdown();
});
