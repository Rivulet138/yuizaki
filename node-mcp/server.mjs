// Minimal HTTP server that exposes Playwright-based browser tools.
// This is intentionally simple: it listens on http://127.0.0.1:7777/tools
// and executes a small set of "browser.*" tools.

import dns from 'node:dns/promises';
import net from 'node:net';
import express from 'express';
import { chromium } from 'playwright';

import { resolveMcpPort } from './config.mjs';

const useStdio = process.argv.includes('--stdio');
const browserTimeoutMs = normalizePositiveInt(process.env.MCP_BROWSER_TIMEOUT_MS, 30000, 1, 120000);
const maxConcurrentBrowsers = normalizePositiveInt(process.env.MCP_MAX_CONCURRENT_BROWSERS, 2, 1, 16);
const maxStdioLineBytes = 64 * 1024;
const maxStdioBufferBytes = 128 * 1024;
const maxRequestIdLength = 128;
const queueTimeoutMs = browserTimeoutMs;
const maxSseClients = 64;
const sseClients = new Set();

function normalizePositiveInt(raw, fallback, min, max) {
  const value = Number.parseInt(String(raw ?? ''), 10);
  return Number.isInteger(value) && value >= min && value <= max ? value : fallback;
}

class Semaphore {
  constructor(limit) {
    this.limit = Number.isInteger(limit) && limit > 0 ? limit : 2;
    this.active = 0;
    this.waiters = [];
  }

  async acquire(timeoutMs = 30000) {
    if (this.active >= this.limit) {
      await new Promise((resolve, reject) => {
        const waiter = { resolve, reject, timer: null, cancelled: false };
        waiter.timer = setTimeout(() => {
          waiter.cancelled = true;
          const index = this.waiters.indexOf(waiter);
          if (index >= 0) this.waiters.splice(index, 1);
          reject(new Error('Browser queue timed out'));
        }, timeoutMs);
        this.waiters.push(waiter);
      });
    }
    this.active += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.active -= 1;
      while (this.waiters.length) {
        const waiter = this.waiters.shift();
        if (waiter.cancelled) continue;
        clearTimeout(waiter.timer);
        waiter.resolve();
        break;
      }
    };
  }
}

const browserSemaphore = new Semaphore(maxConcurrentBrowsers);

const toolManifest = [
  {
    name: 'browser.open_page',
    description: 'Open a URL in a Playwright browser context and wait for network idle.',
    inputSchema: {
      type: 'object',
      properties: {
        url: { type: 'string', description: 'URL to open.' },
      },
      required: ['url'],
    },
  },
  {
    name: 'browser.click',
    description: 'Open a URL and click a CSS selector with Playwright.',
    inputSchema: {
      type: 'object',
      properties: {
        url: { type: 'string', description: 'URL to open before clicking.' },
        selector: { type: 'string', description: 'CSS selector to click.' },
      },
      required: ['selector'],
    },
  },
];

const manifestPayload = {
  tools: toolManifest,
  resources: [],
  prompts: [],
};

class McpInputError extends Error {
  constructor(message) {
    super(message);
    this.name = 'McpInputError';
    this.code = 'INVALID_TOOL_INPUT';
  }
}

function browserUrl(value, fallback) {
  const raw = value === undefined || value === null || value === '' ? fallback : value;
  if (typeof raw !== 'string' || raw.length > 2_048) {
    throw new McpInputError('Browser URL must be a string of at most 2048 characters');
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new McpInputError('Browser URL is invalid');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new McpInputError('Browser URL must use http or https');
  }
  if (parsed.username || parsed.password) {
    throw new McpInputError('Browser URL must not contain credentials');
  }
  return parsed.toString();
}

function browserSelector(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 1_024) {
    throw new McpInputError('Browser selector must be a non-empty string of at most 1024 characters');
  }
  return value;
}

const emitSseEvent = (event, payload) => {
  const frame = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const client of sseClients) {
    if (client.destroyed || !client.writable) {
      sseClients.delete(client);
      continue;
    }
    try {
      client.write(frame);
    } catch {
      sseClients.delete(client);
      client.destroy();
    }
  }
};

const app = express();
app.use(express.json({ limit: '64kb' }));

function isBlockedIp(address) {
  const version = net.isIP(address);
  if (version === 4) {
    const octets = address.split('.').map(Number);
    const [a, b] = octets;
    return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
      (a >= 224) || (a === 100 && b >= 64 && b <= 127);
  }
  if (version === 6) {
    const normalized = address.toLowerCase();
    const mappedV4 = normalized.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    return normalized === '::' || normalized === '::1' || normalized.startsWith('fe80:') ||
      normalized.startsWith('fc') || normalized.startsWith('fd') || normalized.startsWith('ff') ||
      (mappedV4 ? isBlockedIp(mappedV4[1]) : false);
  }
  return true;
}

async function assertSafeBrowserUrl(value) {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new McpInputError('Browser URL must use http or https without credentials');
  }
  const hostname = parsed.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (!hostname || hostname === 'localhost' || hostname.endsWith('.localhost') || net.isIP(hostname) && isBlockedIp(hostname)) {
    throw new McpInputError('Browser URL targets a private or local address');
  }
  let records;
  try {
    records = await dns.lookup(hostname, { all: true, verbatim: true });
  } catch {
    throw new McpInputError('Browser URL hostname could not be resolved');
  }
  if (!records.length || records.some(({ address }) => isBlockedIp(address))) {
    throw new McpInputError('Browser URL targets a private or local address');
  }
  return parsed.toString();
}

function withTimeout(promise, timeoutMs, message = 'Browser operation timed out') {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => clearTimeout(timer));
}

function validateRequestId(value) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > maxRequestIdLength) {
    throw new McpInputError(`requestId must be a non-empty string of at most ${maxRequestIdLength} characters`);
  }
  return value;
}

function publicToolError(err) {
  if (err?.code === 'INVALID_TOOL_INPUT') return err.message;
  if (err?.message === 'Unknown browser tool') return err.message;
  return 'Browser tool failed';
}

async function withBrowser(fn) {
  const release = await browserSemaphore.acquire(queueTimeoutMs);
  let browser;
  try {
    browser = await withTimeout(chromium.launch(), browserTimeoutMs);
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(browserTimeoutMs);
    page.setDefaultNavigationTimeout(browserTimeoutMs);
    await page.route('**/*', async (route) => {
      try {
        const requestUrl = route.request().url();
        if (requestUrl.startsWith('http://') || requestUrl.startsWith('https://')) {
          await assertSafeBrowserUrl(requestUrl);
        }
        await route.continue();
      } catch {
        await route.abort('blockedbyclient');
      }
    });
    return await withTimeout(fn(page), browserTimeoutMs);
  } finally {
    try {
      if (browser) await browser.close();
    } finally {
      release();
    }
  }
}

async function handleToolCall(name, args) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) {
    throw new McpInputError('Tool args must be an object');
  }
  if (name === 'browser.open_page') {
    const url = await assertSafeBrowserUrl(browserUrl(args.url));
    await withBrowser(async (page) => {
      await page.goto(url, { waitUntil: 'networkidle', timeout: browserTimeoutMs });
    });
    return `Opened page: ${url}`;
  }

  if (name === 'browser.click') {
    const selector = browserSelector(args.selector);
    const url = await assertSafeBrowserUrl(browserUrl(args.url, 'https://example.com'));
    await withBrowser(async (page) => {
      await page.goto(url, { waitUntil: 'networkidle', timeout: browserTimeoutMs });
      await page.click(selector, { timeout: browserTimeoutMs });
    });
    return `Clicked ${selector} on ${url}`;
  }

  throw new Error('Unknown browser tool');
}

if (useStdio) {
  let buffer = '';
  let processing = Promise.resolve();
  process.stdin.setEncoding('utf8');
  const processLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    processing = processing.then(async () => {
      let payload;
      let requestId = null;
      try {
        payload = JSON.parse(trimmed);
        requestId = validateRequestId(payload?.requestId);
        const output = await handleToolCall(payload.name, payload.args || {});
        process.stdout.write(`${JSON.stringify({ ok: true, output, requestId })}\n`);
      } catch (err) {
        process.stdout.write(`${JSON.stringify({ ok: false, error: publicToolError(err), requestId })}\n`);
      }
    });
  };
  process.stdin.on('data', (chunk) => {
    buffer += chunk;
    if (Buffer.byteLength(buffer) > maxStdioBufferBytes) {
      process.stdout.write(`${JSON.stringify({ ok: false, error: 'stdio input buffer exceeded limit', requestId: null })}\n`);
      process.stdin.pause();
      return;
    }
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (Buffer.byteLength(line) > maxStdioLineBytes) {
        process.stdout.write(`${JSON.stringify({ ok: false, error: 'stdio input line exceeded limit', requestId: null })}\n`);
        continue;
      }
      processLine(line);
    }
  });
  process.stdin.on('end', () => {
    if (buffer.trim()) {
      if (Buffer.byteLength(buffer) <= maxStdioLineBytes) processLine(buffer);
      else process.stdout.write(`${JSON.stringify({ ok: false, error: 'stdio input line exceeded limit', requestId: null })}\n`);
    }
  });
} else {
  app.get('/health', (_req, res) => {
    res.json({ ok: true });
  });

  app.get('/manifest', (_req, res) => {
    res.json(manifestPayload);
  });

  app.get('/tools', (_req, res) => {
    res.json({ tools: toolManifest });
  });

  app.get('/events', (req, res) => {
    if (sseClients.size >= maxSseClients) {
      return res.status(503).json({ ok: false, error: 'Too many SSE clients' });
    }
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders?.();

    res.write('event: ready\ndata: {"ok":true}\n\n');
    sseClients.add(res);

    const cleanup = () => sseClients.delete(res);
    req.on('close', cleanup);
    res.on('error', cleanup);
    res.on('finish', cleanup);
  });

  app.post('/tools', async (req, res) => {
    const { name, args, requestId: rawRequestId } = req.body || {};
    let requestId;
    try { requestId = validateRequestId(rawRequestId); } catch (err) {
      return res.status(400).json({ ok: false, error: publicToolError(err), requestId: null });
    }
    if (!name) {
      return res.status(400).json({ ok: false, error: 'Missing tool name' });
    }

    try {
      const output = await handleToolCall(name, args || {});
      const payload = { ok: true, output, requestId };
      if (requestId) {
        emitSseEvent('tool-result', payload);
      }
      res.json(payload);
    } catch (err) {
      console.error('[MCP] Tool error:', err);
      const payload = { ok: false, error: publicToolError(err), requestId };
      if (requestId) {
        emitSseEvent('tool-result', payload);
      }
      res.status(err?.code === 'INVALID_TOOL_INPUT' ? 400 : 500).json(payload);
    }
  });

  app.use((err, _req, res, _next) => {
    if (err?.type === 'entity.too.large' || err instanceof SyntaxError) {
      return res.status(400).json({ ok: false, error: 'Invalid JSON request body', requestId: null });
    }
    console.error('[MCP] HTTP error:', err);
    return res.status(500).json({ ok: false, error: 'Request failed', requestId: null });
  });

  const PORT = resolveMcpPort();
  app.listen(PORT, '127.0.0.1', () => {
    console.log(`Playwright MCP server listening on http://127.0.0.1:${PORT}`);
  });
}
