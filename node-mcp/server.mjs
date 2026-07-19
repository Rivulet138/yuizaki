// Minimal HTTP server that exposes Playwright-based browser tools.
// This is intentionally simple: it listens on http://127.0.0.1:7777/tools
// and executes a small set of "browser.*" tools.

import express from 'express';
import { chromium } from 'playwright';

import { resolveMcpPort } from './config.mjs';

const useStdio = process.argv.includes('--stdio');
const sseClients = new Set();

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

const emitSseEvent = (event, payload) => {
  const frame = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const client of sseClients) {
    client.write(frame);
  }
};

const app = express();
app.use(express.json());

async function withBrowser(fn) {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    return await fn(page);
  } finally {
    await browser.close();
  }
}

async function handleToolCall(name, args) {
  if (name === 'browser.open_page') {
    const url = args.url || 'https://example.com';
    await withBrowser(async (page) => {
      await page.goto(url, { waitUntil: 'networkidle' });
    });
    return `Opened page: ${url}`;
  }

  if (name === 'browser.click') {
    const url = args.url || 'https://example.com';
    const selector = args.selector || 'body';
    await withBrowser(async (page) => {
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.click(selector);
    });
    return `Clicked ${selector} on ${url}`;
  }

  throw new Error(`Unknown browser tool: ${name}`);
}

if (useStdio) {
  let buffer = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', async (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const payload = JSON.parse(trimmed);
        const output = await handleToolCall(payload.name, payload.args || {});
        process.stdout.write(`${JSON.stringify({ ok: true, output })}\n`);
      } catch (err) {
        process.stdout.write(`${JSON.stringify({ ok: false, error: String(err) })}\n`);
      }
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
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders?.();

    res.write('event: ready\ndata: {"ok":true}\n\n');
    sseClients.add(res);

    req.on('close', () => {
      sseClients.delete(res);
    });
  });

  app.post('/tools', async (req, res) => {
    const { name, args, requestId } = req.body || {};
    if (!name) {
      return res.status(400).json({ ok: false, error: 'Missing tool name' });
    }

    try {
      const output = await handleToolCall(name, args || {});
      const payload = { ok: true, output, requestId: requestId || null };
      if (requestId) {
        emitSseEvent('tool-result', payload);
      }
      res.json(payload);
    } catch (err) {
      console.error('[MCP] Tool error:', err);
      const payload = { ok: false, error: String(err), requestId: requestId || null };
      if (requestId) {
        emitSseEvent('tool-result', payload);
      }
      res.status(500).json(payload);
    }
  });

  const PORT = resolveMcpPort();
  app.listen(PORT, '127.0.0.1', () => {
    console.log(`Playwright MCP server listening on http://127.0.0.1:${PORT}`);
  });
}
