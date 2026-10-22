#!/usr/bin/env node
/**
 * Minimal MCP (Model Context Protocol) server for the local Yuizaki backend.
 *
 * Transport: newline-delimited JSON-RPC 2.0 on stdio. Nothing but protocol
 * frames is ever written to stdout; diagnostics go to stderr.
 *
 * Scope: loopback Yuizaki HTTP API only. This process never proxies arbitrary
 * URLs and never reads Yuizaki credentials.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const PROTOCOL_VERSION = '2025-06-18';
const SERVER_INFO = { name: 'yuizaki', version: '0.1.0' };
const DEFAULT_BASE_URL = 'http://127.0.0.1:8001';
const MAX_TEXT = 12000;
const DEFAULT_TIMEOUT_MS = 8000;
const CHAT_TIMEOUT_MS = 120000;
const START_TIMEOUT_MS = 90000;

class ToolFailure extends Error {
  constructor(message) {
    super(message);
    this.name = 'ToolFailure';
  }
}

function log(message) {
  process.stderr.write(`[yuizaki-mcp] ${message}\n`);
}

function truncate(text, limit = MAX_TEXT) {
  const value = String(text ?? '');
  if (value.length <= limit) return value;
  const marker = '\n...[truncated]...\n';
  const remaining = Math.max(limit - marker.length, 0);
  const head = Math.ceil(remaining / 2);
  const tail = Math.floor(remaining / 2);
  return value.slice(0, head) + marker + (tail > 0 ? value.slice(-tail) : '');
}

/** Reject anything that is not an explicit loopback target. */
function resolveBaseUrl(raw) {
  const value = String(raw ?? DEFAULT_BASE_URL).trim() || DEFAULT_BASE_URL;
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new ToolFailure(`YUIZAKI_BASE_URL is not a valid URL: ${value}`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ToolFailure('YUIZAKI_BASE_URL must use http or https');
  }
  const host = parsed.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  const loopback = host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.localhost');
  if (!loopback) {
    throw new ToolFailure('YUIZAKI_BASE_URL must point at loopback; remote hosts are not supported');
  }
  return parsed.origin + parsed.pathname.replace(/\/+$/, '');
}

const BASE_URL = () => resolveBaseUrl(process.env.YUIZAKI_BASE_URL);

async function requestJson(pathname, { method = 'GET', body, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const url = `${BASE_URL()}${pathname}`;
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? {} : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (error?.name === 'TimeoutError') {
      throw new ToolFailure(`Yuizaki request timed out after ${timeoutMs}ms: ${method} ${pathname}`);
    }
    throw new ToolFailure(`Yuizaki is not reachable at ${BASE_URL()}: ${error?.message ?? error}`);
  }
  const raw = await response.text();
  let parsed = null;
  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const detail = parsed && typeof parsed === 'object'
      ? (parsed.error?.message || parsed.error || parsed.detail || '')
      : truncate(raw, 600);
    throw new ToolFailure(`Yuizaki ${method} ${pathname} failed with ${response.status}: ${truncate(detail, 600)}`);
  }
  return parsed ?? {};
}

async function ping() {
  try {
    const payload = await requestJson('/api/ping', { timeoutMs: 3000 });
    return { reachable: true, payload };
  } catch (error) {
    return { reachable: false, error: error.message };
  }
}

function repoRoot() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.resolve(here, '..', '..');
}

function launcherPath() {
  const configured = process.env.YUIZAKI_LAUNCHER;
  if (configured) return configured;
  const root = repoRoot();
  const candidates = process.platform === 'win32'
    ? [path.join(root, 'YuizakiLauncher.exe'), path.join(root, 'YuizakiLauncher')]
    : [path.join(root, 'YuizakiLauncher')];
  return candidates.find((candidate) => existsSync(candidate)) ?? candidates[0];
}

function runLauncher(args, { timeoutMs = 20000 } = {}) {
  return new Promise((resolve) => {
    const command = launcherPath();
    if (!existsSync(command)) {
      resolve({ ok: false, code: null, output: `Launcher not found: ${command}` });
      return;
    }
    let child;
    try {
      child = spawn(command, args, { cwd: repoRoot(), windowsHide: true });
    } catch (error) {
      resolve({ ok: false, code: null, output: String(error?.message ?? error) });
      return;
    }
    let output = '';
    const collect = (chunk) => {
      output = (output + chunk.toString('utf8')).slice(-8000);
    };
    child.stdout?.on('data', collect);
    child.stderr?.on('data', collect);
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* ignore */ }
      resolve({ ok: false, code: null, output: `${output}\n[launcher timed out after ${timeoutMs}ms]` });
    }, timeoutMs);
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ ok: false, code: null, output: String(error?.message ?? error) });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, output });
    });
  });
}

function spawnSupervisor() {
  const command = launcherPath();
  if (!existsSync(command)) {
    throw new ToolFailure(`Launcher not found: ${command}`);
  }
  const child = spawn(command, ['start'], {
    cwd: repoRoot(),
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
  });
  child.unref();
  return { command, pid: child.pid ?? null };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let cachedModel = null;

async function effectiveModel() {
  const override = String(process.env.YUIZAKI_MODEL ?? '').trim();
  if (override) return override;
  if (cachedModel) return cachedModel;
  let payload;
  try {
    payload = await requestJson('/v1/models', { timeoutMs: 4000 });
  } catch (error) {
    // Surface the transport failure (offline backend) instead of blaming the model.
    throw error instanceof ToolFailure ? error : new ToolFailure(String(error?.message ?? error));
  }
  const id = payload?.data?.[0]?.id;
  if (typeof id === 'string' && id.trim()) {
    cachedModel = id.trim();
    return cachedModel;
  }
  throw new ToolFailure('Yuizaki did not report a model id; set YUIZAKI_MODEL');
}

const tools = [
  {
    name: 'yuizaki_status',
    description: 'Report whether the local Yuizaki backend is running and summarize its companion runtime projection.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
    handler: async () => {
      const health = await ping();
      if (!health.reachable) {
        return `Yuizaki backend: offline\nbase_url: ${BASE_URL()}\ndetail: ${health.error}`;
      }
      const lines = [`Yuizaki backend: online (${BASE_URL()})`];
      try {
        const runtime = await requestJson('/api/system/companion-runtime', { timeoutMs: 5000 });
        const summary = {
          workspace: runtime?.active_workspace_id ?? undefined,
          companion: runtime?.active_companion?.name ?? runtime?.active_companion?.id ?? undefined,
          heartbeat: runtime?.heartbeat?.running ?? undefined,
          companion_state: runtime?.companion_state ?? undefined,
          memory: runtime?.memory_state ?? undefined,
          retrieval: runtime?.retrieval_strategy?.label ?? undefined,
          active_jobs: Array.isArray(runtime?.jobs?.active_job_ids) ? runtime.jobs.active_job_ids.length : undefined,
          job_events: Array.isArray(runtime?.jobs?.events) ? runtime.jobs.events.length : undefined,
        };
        const events = Array.isArray(runtime?.jobs?.events) ? runtime.jobs.events.slice(-3) : [];
        if (events.length) {
          summary.recent_jobs = events.map((job) => ({
            id: job?.job_id ?? job?.jobId,
            status: job?.status,
            tool: job?.tool_name ?? job?.toolName,
          }));
        }
        lines.push(`runtime: ${truncate(JSON.stringify(summary), 3000)}`);
      } catch (error) {
        lines.push(`runtime projection unavailable: ${error.message}`);
      }
      return lines.join('\n');
    },
  },
  {
    name: 'yuizaki_start',
    description: 'Start the local Yuizaki desktop app (launcher supervisor) and wait until its backend answers /api/ping. Pass dryRun to inspect without spawning.',
    inputSchema: {
      type: 'object',
      properties: {
        dryRun: { type: 'boolean', description: 'Report what would run without starting anything' },
        timeoutSeconds: { type: 'integer', minimum: 5, maximum: 180, description: 'How long to wait for the backend' },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const timeoutSeconds = Number.isInteger(args.timeoutSeconds) ? args.timeoutSeconds : 60;
      const command = launcherPath();
      if (args.dryRun === true) {
        return [
          'dry-run: not starting anything',
          `launcher: ${command}${existsSync(command) ? '' : ' (missing)'}`,
          `cwd: ${repoRoot()}`,
          `argv: ${JSON.stringify(['start'])}`,
          `base_url: ${BASE_URL()}`,
        ].join('\n');
      }
      const health = await ping();
      if (health.reachable) return `Yuizaki is already running at ${BASE_URL()}; nothing to start.`;
      const status = await runLauncher(['status'], { timeoutMs: 15000 });
      if (!/status:\s*stopped/i.test(status.output) && status.ok) {
        // Supervisor is alive but the HTTP port is not answering yet.
        for (let waited = 0; waited < timeoutSeconds; waited += 1) {
          await sleep(1000);
          if ((await ping()).reachable) return `Yuizaki backend is online at ${BASE_URL()} (supervisor already running).`;
        }
        return `Supervisor is running but the backend did not answer within ${timeoutSeconds}s.\nlauncher status:\n${truncate(status.output, 2000)}`;
      }
      const spawned = spawnSupervisor();
      for (let waited = 0; waited < timeoutSeconds; waited += 1) {
        await sleep(1000);
        if ((await ping()).reachable) {
          return `Yuizaki backend is online at ${BASE_URL()} (launcher pid ${spawned.pid ?? 'unknown'}).`;
        }
      }
      const after = await runLauncher(['status'], { timeoutMs: 15000 });
      return `Started the launcher but the backend did not answer within ${timeoutSeconds}s.\nlauncher status:\n${truncate(after.output, 2000)}`;
    },
  },
  {
    name: 'yuizaki_chat',
    description: 'Send one message to the running Yuizaki companion and return its reply. Uses the configured Yuizaki provider and keeps its session, workspace, and memory behavior.',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string', minLength: 1, maxLength: 4000, description: 'Message text for the companion' },
        sessionId: { type: 'string', maxLength: 200, description: 'Optional Yuizaki session id to continue' },
        workspaceId: { type: 'string', maxLength: 200, description: 'Optional workspace id' },
        autonomyMode: {
          type: 'string',
          enum: ['companion', 'assistant', 'executor', 'reflector', 'silent'],
          description: 'Yuizaki autonomy mode; defaults to the server default (companion)',
        },
      },
      required: ['message'],
      additionalProperties: false,
    },
    handler: async (args) => {
      const message = String(args.message ?? '').trim();
      if (!message) throw new ToolFailure('message must not be empty');
      const body = {
        model: await effectiveModel(),
        messages: [{ role: 'user', content: message }],
        stream: false,
      };
      if (args.sessionId) body.session_id = String(args.sessionId);
      if (args.workspaceId) body.workspace_id = String(args.workspaceId);
      if (args.autonomyMode) body.autonomy_mode = String(args.autonomyMode);
      const payload = await requestJson('/v1/chat/completions', {
        method: 'POST',
        body,
        timeoutMs: CHAT_TIMEOUT_MS,
      });
      const choice = payload?.choices?.[0];
      const reply = choice?.message?.content ?? '';
      const outcome = payload?.outcome ?? 'unknown';
      const lines = [String(reply || '(empty reply)')];
      lines.push(`outcome: ${outcome}`);
      if (payload?.turn_commit?.session_id) lines.push(`session_id: ${payload.turn_commit.session_id}`);
      if (outcome !== 'known_success' && outcome !== 'success') {
        lines.push(`warning: turn outcome was ${outcome}; treat the reply as unconfirmed.`);
      }
      return truncate(lines.join('\n'));
    },
  },
  {
    name: 'yuizaki_memory_query',
    description: 'Search Yuizaki long-term memory (read-only semantic recall) and return the top matches.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', minLength: 1, maxLength: 1000, description: 'What to recall' },
        topK: { type: 'integer', minimum: 1, maximum: 20, description: 'Number of memories to return (default 5)' },
        workspaceId: { type: 'string', maxLength: 200, description: 'Optional workspace scope' },
      },
      required: ['query'],
      additionalProperties: false,
    },
    handler: async (args) => {
      const query = String(args.query ?? '').trim();
      if (!query) throw new ToolFailure('query must not be empty');
      const body = { query, top_k: Number.isInteger(args.topK) ? args.topK : 5 };
      if (args.workspaceId) body.workspace_id = String(args.workspaceId);
      const payload = await requestJson('/memory/query', { method: 'POST', body, timeoutMs: 20000 });
      if (payload?.error) {
        throw new ToolFailure(`memory recall failed: ${payload.error}`);
      }
      const docs = Array.isArray(payload?.docs) ? payload.docs : [];
      if (!docs.length) return `No memory matched "${truncate(query, 200)}" (recall completed).`;
      const rows = docs.slice(0, body.top_k).map((doc, index) => {
        const id = doc?.id ?? doc?.doc_id ?? `#${index + 1}`;
        const text = doc?.text ?? doc?.content ?? doc?.page_content ?? '';
        const score = typeof doc?.score === 'number' ? doc.score.toFixed(3) : 'n/a';
        return `- [${id}] (score ${score}) ${truncate(text, 400)}`;
      });
      return truncate(`${docs.length} match(es) for "${truncate(query, 200)}":\n${rows.join('\n')}`);
    },
  },
  {
    name: 'yuizaki_connector_status',
    description: 'Report Yuizaki message-connector configuration and account state. Secrets are never returned by the backend.',
    inputSchema: {
      type: 'object',
      properties: {
        connectorId: {
          type: 'string',
          enum: ['qq', 'wechat', 'telegram', 'discord'],
          description: 'Connector to inspect; defaults to qq',
        },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const connectorId = String(args.connectorId ?? 'qq');
      const config = await requestJson(`/api/system/connectors/${connectorId}/config`, { timeoutMs: 5000 });
      const lines = [`connector: ${connectorId}`, `config: ${truncate(JSON.stringify(config?.config ?? config), 2500)}`];
      if (connectorId === 'qq' || connectorId === 'wechat') {
        try {
          const account = await requestJson(`/api/system/connectors/${connectorId}/account`, { timeoutMs: 5000 });
          lines.push(`account: ${truncate(JSON.stringify(account?.account ?? account), 1200)}`);
        } catch (error) {
          lines.push(`account: unavailable (${error.message})`);
        }
      }
      return lines.join('\n');
    },
  },
];

const toolIndex = new Map(tools.map((tool) => [tool.name, tool]));

function textResult(text, isError = false) {
  return { content: [{ type: 'text', text: truncate(String(text)) }], isError };
}

async function callTool(name, args) {
  const tool = toolIndex.get(name);
  if (!tool) {
    throw Object.assign(new Error(`Unknown tool: ${name}`), { code: -32602 });
  }
  const input = args && typeof args === 'object' ? args : {};
  try {
    const text = await tool.handler(input);
    return textResult(text, false);
  } catch (error) {
    log(`tool ${name} failed: ${error?.message ?? error}`);
    return textResult(`error: ${error?.message ?? String(error)}`, true);
  }
}

async function dispatch(message) {
  const { id, method, params } = message ?? {};
  const isRequest = id !== undefined && id !== null;
  try {
    switch (method) {
      case 'initialize':
        return {
          jsonrpc: '2.0',
          id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: { tools: { listChanged: false } },
            serverInfo: SERVER_INFO,
            instructions: 'Local Yuizaki companion bridge. Tools act on the loopback Yuizaki backend only.',
          },
        };
      case 'notifications/initialized':
      case 'notifications/cancelled':
        return null;
      case 'ping':
        return { jsonrpc: '2.0', id, result: {} };
      case 'tools/list':
        return {
          jsonrpc: '2.0',
          id,
          result: {
            tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
          },
        };
      case 'tools/call': {
        const name = params?.name;
        if (typeof name !== 'string' || !name) {
          return { jsonrpc: '2.0', id, error: { code: -32602, message: 'tools/call requires a tool name' } };
        }
        const result = await callTool(name, params?.arguments);
        return { jsonrpc: '2.0', id, result };
      }
      default:
        if (!isRequest) return null;
        return { jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } };
    }
  } catch (error) {
    if (!isRequest) return null;
    const code = Number.isInteger(error?.code) ? error.code : -32603;
    return { jsonrpc: '2.0', id, error: { code, message: String(error?.message ?? error) } };
  }
}

function respond(payload) {
  if (payload === null || payload === undefined) return;
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

async function handleLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return;
  let message;
  try {
    message = JSON.parse(trimmed);
  } catch {
    respond({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
    return;
  }
  if (Array.isArray(message)) {
    for (const item of message) {
      respond(await dispatch(item));
    }
    return;
  }
  respond(await dispatch(message));
}

function serve() {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let pending = Promise.resolve();
  rl.on('line', (line) => {
    // Serialize handling so replies stay ordered per request.
    pending = pending.then(() => handleLine(line)).catch((error) => {
      log(`fatal line handling error: ${error?.message ?? error}`);
    });
  });
  rl.on('close', () => {
    pending.finally(() => process.exit(0));
  });
  process.on('SIGINT', () => process.exit(0));
  process.on('SIGTERM', () => process.exit(0));
  // A bad base URL must fail per call, not at start-up: exiting here would
  // look like a transport crash to the MCP client.
  try {
    log(`ready (base ${BASE_URL()})`);
  } catch (error) {
    log(`base url rejected: ${error?.message ?? error}`);
  }
}

async function selftest() {
  const report = [];
  let failed = false;
  try {
    report.push(`base_url: ${BASE_URL()}`);
  } catch (error) {
    report.push(`base_url: INVALID (${error.message})`);
    failed = true;
  }
  report.push(`launcher: ${launcherPath()} (${existsSync(launcherPath()) ? 'found' : 'missing'})`);
  const health = await ping();
  report.push(`backend: ${health.reachable ? 'online' : 'offline'}`);
  if (!health.reachable) failed = true;
  if (health.reachable) {
    try {
      report.push(`model: ${await effectiveModel()}`);
    } catch (error) {
      report.push(`model: unknown (${error.message})`);
      failed = true;
    }
    for (const tool of tools) {
      report.push(`tool: ${tool.name} ok`);
    }
  }
  report.push(`tools: ${tools.length}`);
  process.stdout.write(`${report.join('\n')}\n`);
  process.exit(failed ? 1 : 0);
}

const isMain = Boolean(process.argv[1]) && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain && process.argv.includes('--selftest')) {
  selftest();
} else if (isMain && process.argv.includes('--help')) {
  process.stdout.write('yuizaki-mcp: stdio MCP server for the local Yuizaki backend. Use --selftest to probe.\n');
} else if (isMain) {
  serve();
}

export { tools, truncate, resolveBaseUrl, dispatch };
