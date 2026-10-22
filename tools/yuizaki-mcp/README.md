# yuizaki-mcp

A small MCP (Model Context Protocol) server that exposes the local Yuizaki
companion backend to DSH and other MCP clients. It is a **stdio** server with no
dependencies: `node server.mjs`.

It only ever talks to a loopback Yuizaki backend (`127.0.0.1`, `localhost`,
`[::1]`). A non-loopback `YUIZAKI_BASE_URL` is rejected per call; it never
becomes a general HTTP proxy and it never reads Yuizaki credentials.

## Tools

| Tool | Side effect | Purpose |
| --- | --- | --- |
| `yuizaki_status` | read | Backend reachability plus a bounded companion-runtime summary |
| `yuizaki_start` | spawns the launcher | Start Yuizaki and wait for `/api/ping`; `dryRun: true` only reports the plan |
| `yuizaki_chat` | Agent turn | Send one message as the companion and return its reply |
| `yuizaki_memory_query` | read | Semantic recall over long-term memory |
| `yuizaki_connector_status` | read | Connector configuration and account state (secrets are never returned) |

`yuizaki_chat` reuses the model id that Yuizaki reports on `GET /v1/models`, so
the bridge cannot silently pin a different model than the backend is configured
with. Set `YUIZAKI_MODEL` only to override that on purpose.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `YUIZAKI_BASE_URL` | `http://127.0.0.1:8001` | Backend origin; must be loopback |
| `YUIZAKI_LAUNCHER` | `<repo>/YuizakiLauncher[.exe]` | Launcher used by `yuizaki_start` |
| `YUIZAKI_MODEL` | discovered from `/v1/models` | Override the chat model id |

## Run

```powershell
node tools/yuizaki-mcp/server.mjs --selftest   # probe backend, launcher, model
node tools/yuizaki-mcp/server.mjs              # serve MCP over stdio
cd tools/yuizaki-mcp; npm test                  # run the test suite
```

Run the tests from inside `tools/yuizaki-mcp`: `node --test <dir>` from the repo
root resolves the directory as a single entry point and silently runs only one
file.

`--selftest` exits non-zero when the backend is offline, so it is safe to use in
a health check.

## Register with DSH

Add one MCP client plugin to `~/.dsh/profiles/<profile>/cordis.patch.yml`
(back the file up first; DSH hot-reloads it when `dsh-hmr` is enabled):

```yaml
    - id: mcp-yuizaki
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: yuizaki
        transport: stdio
        command: node
        args: [ 'E:/yuizaki/tools/yuizaki-mcp/server.mjs' ]
```

Use an absolute path that matches your checkout. The server writes protocol
frames to stdout and diagnostics to stderr, so DSH can supervise it like any
other stdio MCP server.

## Boundaries

- These tools act on the user's own desktop app: `yuizaki_chat` starts a real
  Agent turn (tokens, TTS, memory writes) and `yuizaki_start` launches processes.
- `yuizaki_start` uses `launcher status` to avoid spawning a second supervisor.
- Every reply is truncated, and errors are returned as tool errors instead of
  throwing, so a broken backend cannot crash the client session.
- This server does not expose Yuizaki's tool execution, plugin configuration, or
  credential state; it is a control and query surface, not an admin console.
