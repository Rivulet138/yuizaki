# DSH and OneBot Integration

This note records runtime contracts and failure semantics for the optional DSH
coding delegate and QQ OneBot connector. It is an implementation guide, not a
claim that external OpenLux, DSH, or OneBot services have been qualified.

## Provider credentials (WP1)

For OpenLux, configure the active provider as `custom`, endpoint
`https://api.openlux.ai/v1`, and model `deepseek-v4.1-flash`. Supply the Yuizaki
LLM key through `YUIZAKI_PROVIDER_CREDENTIALS_JSON`, for example:

```powershell
$env:YUIZAKI_PROVIDER_CREDENTIALS_JSON = '{"llm.api_key":"<provider-key>"}'
```

Do not commit the key or put it in a DSH task. The application credential vault
is separate from DSH's own `headless` profile credentials. Provider or endpoint
switches must not silently reuse credentials from another provider. A masked or
empty unchanged settings value means preserve the current secret; an explicit
provider credential import is normalized to its canonical field before vault
storage. An empty vault supplied by the launcher must override, not inherit, a
parent-process credential variable.

These rules apply to bulk PATCH, single-setting writes/deletes, and both
history rollback paths, including the separate vision connection. Rollback may
preserve the current secret only when normalized provider and endpoint match;
it cannot restore a key from a different connection. Explicit credential DELETE
clears the runtime key even if persisted settings already contain an empty
placeholder. Ordinary empty/masked PATCH values still preserve the current key.

## DSH execution boundary (WP2)

`ask_dsh` is an explicitly requested coding capability, not a chat fallback.
It can edit real workspace files, so it is registered as `risk_level="high"`,
`effect_kind="write"`, and requires `policy_engine` user confirmation for each
execution. Do not weaken this to remembered approval for an unknown write.

The subprocess API is an argv list with `shell=False`; task text is one argument,
not interpolated into a command string. Reject empty tasks and task arguments
whose first non-whitespace character is `-` so task text cannot become a DSH CLI
option. On Windows, launch Node with the DSH JS entry point; Windows
`CreateProcess` cannot directly execute `dsh.cmd`:

```text
node <npm-root>/node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless <task>
```

Use the same inherited environment allowlist as
`mcp_manager._stdio_process_env()`, adding only explicitly supported DSH provider
key variables. Never forward any `YUIZAKI_*` variable. Yuizaki's OpenLux key is
therefore not implicitly inherited by DSH.

Only one invocation runs at a time; queue wait and execution have finite
deadlines. Timeout and cancellation terminate the owned process tree and bound
pipe draining so orphaned descendants cannot hold the semaphore forever.
Successful completion also closes the process-tree guard. Output is redacted
before it enters the bounded head/tail retention buffer; the reported raw
character count is independent of redaction. Job progress uses the existing
`CompanionJobEventLog` UI projection, which is in-memory and bounded, not a
durable audit log. Authorization redaction recognizes schemes and quoted values
across arbitrary output chunk boundaries. Reader failures drain or cancel and
await sibling reader/waiter tasks before releasing admission.

High/critical tools always require a fresh approval even if an earlier allow was
remembered. Permission persistence must succeed before releasing the execution
future. Permission callback failure, cancellation signals, and direct task
cancellation terminate the job and clear pending approval. Retry is offered only
when the server marks the job retryable and the original arguments are available;
redacted argument receipts cannot be replayed. The UI follows the same contract.

The DSH profile persists independently under `~/.dsh`. A nonzero exit, timeout,
I/O failure, or empty output may happen after a write; report it as an
`unknown_effect` where appropriate, inspect workspace state, and do not retry
automatically.

## OneBot ingress and delivery (WP3)

The QQ adapter rejects self-originated events and non-message `post_type`s.
For groups, `mentionRequired` means an actual `at` segment addressed to
`self_id`; textual lookalikes and mentions to other users do not qualify.
`allowedUsers` and `allowedGroups` are checked before Agent work. Media segments
remain visible as `[图片]`, `[语音]`, or `[文件]`, rather than becoming an empty
prompt. CQ string forms are parsed as segments, including CQ escaping.

Per-session rate admission returns HTTP 2xx with `accepted: false` and
`reason: "rate_limited"`; returning a failure status here can cause bridge
redelivery storms. Recovered/retried work must pass current enablement,
allowlists, and the same concurrent admission checks as new work.

For OneBot 11 HTTP action responses, only `status="ok", retcode=0` confirms
success. `status="async", retcode=1` only acknowledges submission; the final
effect is unknown and must not be marked delivered or blindly retried.
`status="failed"` and invalid status/retcode combinations are not success.
If the POST may have reached the bridge but its response cannot be read or
parsed, preserve `sending`/unknown state. Without a remote idempotency key, a
retry or expired lease could send a duplicate. OneBot 12 and generic bridges
retain their own response contracts.

Cancelling an await on a threaded HTTP POST cannot stop a request already in
flight. Manual retry cancellation therefore retains unknown delivery. The same
applies if the remote send succeeds but committing the local sent state fails.
Both ingress and manual retry paths refuse a second send from this ambiguous
state. Outbound OneBot 11 string messages use `auto_escape=true`, so model text
such as `[CQ:at,qq=all]` remains literal rather than executing a CQ action.

## Design references

These sources informed specific choices; they do not prove this integration is
secure or correct in every deployment.

- [OneBot 11 HTTP communication](https://github.com/botuniverse/onebot-11/blob/master/communication/http.md)
  distinguishes completed `ok` results from `async` submission and `failed`
  results; transport HTTP success alone does not mark delivery.
- [OneBot 11 public APIs](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)
  define `auto_escape` for string messages; plain model output must not become
  executable CQ instructions.
- [VS Code process management](https://github.com/microsoft/vscode/blob/main/src/vs/base/node/processes.ts)
  provides a process-tree cleanup comparison. Yuizaki uses suspended launch and
  Windows Job Objects to attach ownership before DSH can spawn descendants.
- [Python asyncio tasks](https://docs.python.org/3/library/asyncio-task.html)
  inform cancellation handling around synchronous HTTP delegated to a thread.
- [NoneBot OneBot adapter](https://github.com/nonebot/adapter-onebot) provides
  an implementation example of interpreting the OneBot action result envelope.
- [OneBot CQ Code specification](https://github.com/botuniverse/onebot-11/blob/master/message/segment.md)
  defines segment types and escaping relevant to `at` and media parsing.
- [Python asyncio subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html)
  documents subprocess and pipe lifecycle behavior; [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
  support owning a Windows child process tree.
- [AWS: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
  explains why a lost response is ambiguous unless the receiver offers
  idempotency. This motivates retaining an unknown/sending state.
- [InjecAgent](https://arxiv.org/abs/2403.02691) studies indirect prompt
  injection through tool-connected agents; [AgentDojo](https://arxiv.org/abs/2406.13352)
  evaluates attacks and defenses over untrusted tool data. These motivate
  treating delegated task context and tool output as untrusted and retaining
  explicit approval for real writes. Neither paper is a Yuizaki security
  certification.

## Verification boundary

Repository regression tests cover deterministic command construction,
environment filtering, output redaction/limits, process cleanup, permission and
retry states, OneBot parsing, allowlists, and admission behavior. They do not
replace a live test with a configured OpenLux key, installed DSH headless
profile, or authenticated OneBot bridge. Do not record those external flows as
passed unless they have been run in the target deployment.

The final repository validation and remaining static-analysis baseline are
recorded in [the integration review](DSH_INTEGRATION_REVIEW.md).
