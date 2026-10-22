import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { resolveBaseUrl, tools, truncate } from './server.mjs';

const SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), 'server.mjs');

/** Minimal fake Yuizaki backend that records what the bridge asked for. */
function startFakeBackend() {
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      const record = { method: req.method, url: req.url, body: body ? JSON.parse(body) : null };
      seen.push(record);
      const send = (status, payload) => {
        res.writeHead(status, { 'content-type': 'application/json' });
        res.end(JSON.stringify(payload));
      };
      if (req.url === '/api/ping') return send(200, { ok: true, status: 'ok' });
      if (req.url === '/api/system/companion-runtime') {
        return send(200, {
          active_workspace_id: 'default',
          active_companion: { id: 'companion-1', name: '结崎' },
          heartbeat: { running: true, tick_count: 3 },
          companion_state: { mood: 'calm', energy: 0.8 },
          memory_state: { semantic_count: 12 },
          retrieval_strategy: { label: 'hybrid' },
          jobs: {
            active_job_ids: [],
            events: [{ job_id: 'job-1', status: 'completed', tool_name: 'ask_dsh' }],
          },
        });
      }
      if (req.url === '/v1/models') return send(200, { object: 'list', data: [{ id: 'deepseek-v4.1-flash', object: 'model' }] });
      if (req.url === '/v1/chat/completions') {
        return send(200, {
          choices: [{ message: { role: 'assistant', content: '你好，我是结崎。' } }],
          outcome: 'known_success',
          turn_commit: { session_id: record.body?.session_id ?? 'default' },
        });
      }
      if (req.url === '/memory/query') {
        return send(200, { query: record.body?.query, docs: [{ id: 'mem-1', text: '用户喜欢安静的音乐', score: 0.91 }] });
      }
      if (req.url === '/api/system/connectors/qq/config') {
        return send(200, { ok: true, config: { id: 'qq', enabled: false, mentionRequired: true, bridgeTokenConfigured: false } });
      }
      if (req.url === '/api/system/connectors/qq/account') {
        return send(200, { ok: true, account: { id: 'qq', connected: false, configured: false } });
      }
      return send(404, { ok: false, error: 'not_found' });
    });
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, port, seen, baseUrl: `http://127.0.0.1:${port}` });
    });
  });
}

/** Spawn the bridge and expose a request/response helper over stdio. */
function startBridge(baseUrl, extraEnv = {}) {
  const child = spawn(process.execPath, [SERVER], {
    env: { ...process.env, YUIZAKI_BASE_URL: baseUrl, ...extraEnv },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const pending = new Map();
  let nextId = 1;
  const rl = createInterface({ input: child.stdout });
  rl.on('line', (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      return;
    }
    const waiter = pending.get(message.id);
    if (waiter) {
      pending.delete(message.id);
      waiter(message);
    }
  });
  child.stderr.resume();
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`bridge did not answer ${method}`));
    }, 15000);
    pending.set(id, (message) => {
      clearTimeout(timer);
      resolve(message);
    });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
  return {
    child,
    request,
    send: (payload) => child.stdin.write(`${payload}\n`),
    close: () => new Promise((resolve) => {
      child.once('exit', resolve);
      child.kill();
    }),
  };
}

test('base URL must stay on loopback', () => {
  assert.equal(resolveBaseUrl('http://127.0.0.1:8001'), 'http://127.0.0.1:8001');
  assert.equal(resolveBaseUrl('http://localhost:8001/'), 'http://localhost:8001');
  assert.equal(resolveBaseUrl(''), 'http://127.0.0.1:8001');
  assert.throws(() => resolveBaseUrl('http://evil.example.com'), /loopback/);
  assert.throws(() => resolveBaseUrl('file:///etc/passwd'), /http or https/);
});

test('truncate keeps both ends and marks the cut', () => {
  const value = 'a'.repeat(100);
  const short = truncate(value, 1000);
  assert.equal(short, value);
  const cut = truncate(value, 20);
  assert.ok(cut.length <= 20);
  assert.ok(cut.includes('[truncated]'));
  assert.ok(cut.startsWith('a'));
});

test('tool catalog is stable and self-describing', () => {
  const names = tools.map((tool) => tool.name);
  assert.deepEqual(names, [
    'yuizaki_status',
    'yuizaki_start',
    'yuizaki_chat',
    'yuizaki_memory_query',
    'yuizaki_connector_status',
  ]);
  for (const tool of tools) {
    assert.equal(tool.inputSchema.type, 'object');
    assert.ok(tool.description.length > 20);
    assert.equal(typeof tool.handler, 'function');
  }
  assert.deepEqual(tools.find((tool) => tool.name === 'yuizaki_chat').inputSchema.required, ['message']);
});

test('stdio protocol: handshake, catalog, calls, and errors', async (t) => {
  const backend = await startFakeBackend();
  const bridge = startBridge(backend.baseUrl);
  t.after(async () => {
    await bridge.close();
    await new Promise((resolve) => backend.server.close(resolve));
  });

  const init = await bridge.request('initialize', { protocolVersion: '2025-06-18', capabilities: {} });
  assert.equal(init.result.protocolVersion, '2025-06-18');
  assert.equal(init.result.serverInfo.name, 'yuizaki');
  assert.ok(init.result.capabilities.tools);

  bridge.send(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }));

  const list = await bridge.request('tools/list', {});
  assert.equal(list.result.tools.length, 5);
  assert.ok(list.result.tools.every((tool) => tool.name.startsWith('yuizaki_')));

  const status = await bridge.request('tools/call', { name: 'yuizaki_status', arguments: {} });
  assert.equal(status.result.isError, false);
  const statusText = status.result.content[0].text;
  assert.match(statusText, /online/);
  assert.match(statusText, /结崎/);
  assert.match(statusText, /ask_dsh/);

  const chat = await bridge.request('tools/call', {
    name: 'yuizaki_chat',
    arguments: { message: '你好', sessionId: 's-1' },
  });
  assert.equal(chat.result.isError, false);
  assert.match(chat.result.content[0].text, /结崎/);
  assert.match(chat.result.content[0].text, /session_id: s-1/);
  const chatCall = backend.seen.find((item) => item.url === '/v1/chat/completions');
  assert.equal(chatCall.body.model, 'deepseek-v4.1-flash', 'bridge must reuse the backend model id');
  assert.equal(chatCall.body.stream, false);
  assert.equal(chatCall.body.session_id, 's-1');

  const memory = await bridge.request('tools/call', { name: 'yuizaki_memory_query', arguments: { query: '音乐', topK: 3 } });
  assert.equal(memory.result.isError, false);
  assert.match(memory.result.content[0].text, /mem-1/);
  assert.equal(backend.seen.find((item) => item.url === '/memory/query').body.top_k, 3);

  const connector = await bridge.request('tools/call', { name: 'yuizaki_connector_status', arguments: {} });
  assert.equal(connector.result.isError, false);
  assert.match(connector.result.content[0].text, /mentionRequired/);

  const unknownTool = await bridge.request('tools/call', { name: 'nope', arguments: {} });
  assert.equal(unknownTool.error.code, -32602);

  const unknownMethod = await bridge.request('tools/dance', {});
  assert.equal(unknownMethod.error.code, -32601);

  const dryRun = await bridge.request('tools/call', { name: 'yuizaki_start', arguments: { dryRun: true } });
  assert.equal(dryRun.result.isError, false);
  assert.match(dryRun.result.content[0].text, /dry-run/);
});

test('bridge reports an offline backend instead of throwing', async (t) => {
  const backend = await startFakeBackend();
  const deadPort = backend.port;
  await new Promise((resolve) => backend.server.close(resolve));
  const bridge = startBridge(`http://127.0.0.1:${deadPort}`);
  t.after(() => bridge.close());

  const status = await bridge.request('tools/call', { name: 'yuizaki_status', arguments: {} });
  assert.equal(status.result.isError, false);
  assert.match(status.result.content[0].text, /offline/);

  const chat = await bridge.request('tools/call', { name: 'yuizaki_chat', arguments: { message: 'hi' } });
  assert.equal(chat.result.isError, true);
  assert.match(chat.result.content[0].text, /not reachable/);
});

test('malformed input is answered with a parse error, not a crash', async (t) => {
  const backend = await startFakeBackend();
  const bridge = startBridge(backend.baseUrl);
  t.after(async () => {
    await bridge.close();
    await new Promise((resolve) => backend.server.close(resolve));
  });
  const reply = new Promise((resolve) => {
    const rl = createInterface({ input: bridge.child.stdout });
    rl.on('line', (line) => {
      const message = JSON.parse(line.trim());
      if (message.error?.code === -32700) resolve(message);
    });
    bridge.send('{not json');
  });
  const message = await reply;
  assert.equal(message.error.code, -32700);
  assert.equal(message.id, null);
});

test('rejects a non-loopback base URL at start-up', async () => {
  const bridge = startBridge('http://198.51.100.7:8001');
  const status = await bridge.request('tools/call', { name: 'yuizaki_status', arguments: {} });
  assert.equal(status.result.isError, true);
  assert.match(status.result.content[0].text, /loopback/);
  await bridge.close();
});
