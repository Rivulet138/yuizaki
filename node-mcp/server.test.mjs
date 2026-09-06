import assert from 'node:assert/strict';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { test, before, after } from 'node:test';

const port = 18000 + Math.floor(Math.random() * 1000);
const baseUrl = `http://127.0.0.1:${port}`;
let server;

before(async () => {
  server = spawn(process.execPath, ['server.mjs'], {
    cwd: new URL('.', import.meta.url),
    env: { ...process.env, MCP_PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('MCP server did not start')), 5000);
    server.stdout.on('data', (chunk) => {
      if (chunk.toString().includes(`:${port}`)) {
        clearTimeout(timeout);
        resolve();
      }
    });
    server.once('error', (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    server.once('exit', (code) => {
      clearTimeout(timeout);
      reject(new Error(`MCP server exited during startup (${code})`));
    });
  });
});

after(async () => {
  if (!server || server.exitCode !== null) return;
  server.kill();
  await once(server, 'exit');
});

test('health endpoint reports a healthy server', async () => {
  const response = await fetch(`${baseUrl}/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test('tools endpoint exposes the browser tool contract', async () => {
  const response = await fetch(`${baseUrl}/tools`);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.ok(Array.isArray(payload.tools));
  assert.deepEqual(
    payload.tools.map((tool) => tool.name),
    ['browser.open_page', 'browser.click'],
  );
  for (const tool of payload.tools) {
    assert.equal(tool.inputSchema.type, 'object');
    assert.ok(Array.isArray(tool.inputSchema.required));
  }
});

test('tools endpoint rejects missing names without invoking a browser', async () => {
  const response = await fetch(`${baseUrl}/tools`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({}),
  });
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { ok: false, error: 'Missing tool name' });
});

test('unknown tools return a structured error and request id', async () => {
  const response = await fetch(`${baseUrl}/tools`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: 'browser.not_real', requestId: 'req-1' }),
  });
  assert.equal(response.status, 500);
  const payload = await response.json();
  assert.equal(payload.ok, false);
  assert.equal(payload.requestId, 'req-1');
  assert.match(payload.error, /Unknown browser tool/);
});

test('browser tools reject non-http URLs before launching a browser', async () => {
  const response = await fetch(`${baseUrl}/tools`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: 'browser.open_page', args: { url: 'file:///etc/passwd' } }),
  });
  assert.equal(response.status, 400);
  const payload = await response.json();
  assert.equal(payload.ok, false);
  assert.match(payload.error, /http or https/);
});

test('browser tools enforce required arguments and reject embedded credentials', async () => {
  for (const args of [{}, { url: 'https://user:secret@example.com' }]) {
    const response = await fetch(`${baseUrl}/tools`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: 'browser.open_page', args }),
    });
    assert.equal(response.status, 400);
    const payload = await response.json();
    assert.equal(payload.ok, false);
    assert.doesNotMatch(payload.error, /user:secret/);
  }
  const response = await fetch(`${baseUrl}/tools`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: 'browser.click', args: {} }),
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /non-empty string/);
});

test('events endpoint sends an SSE ready frame', async () => {
  const response = await fetch(`${baseUrl}/events`);
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /text\/event-stream/);
  const reader = response.body.getReader();
  const { value } = await reader.read();
  await reader.cancel();
  assert.match(new TextDecoder().decode(value), /event: ready\ndata: \{"ok":true\}/);
});
