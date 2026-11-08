# Quality Remediation Evidence and Plan

## Scope and Baseline

- Scope: recording-state binding, renderer type contracts, and the 862 Ruff diagnostics identified in review.
- Baseline on 2026-11-03: clean worktree; direct vue-tsc reports 25 errors in 9 files while the historical-baseline gate passes; Ruff reports 862 diagnostics, including 97 BLE001 and 5 S110 findings.
- A type or lint diagnostic is not automatically a runtime defect. Confirm behavior and boundary contracts before changing exception handling or normalization.

## Ordered Cleanup Plan

1. Add focused regression coverage for confirmed state, identity, and runtime issues before implementation.
2. Repair renderer state propagation and nullable/union contracts using existing interfaces; remove unused event branches.
3. Apply Ruff safe mechanical fixes only, then inspect remaining findings individually. Preserve intentional boundary recovery and cancellation semantics; no blanket ignores or unsafe fixes.
4. Classify broad exception handlers as intentional external/plugin/process boundaries or masking failures. Preserve recovery evidence with logging and tests; narrow catches only where supported by the operations involved.
5. Run targeted tests, full unit tests, lint, direct renderer typecheck, Python tests and static checks. Tighten the renderer baseline only after actual errors are removed.
6. Record final counts, changed behavior, and unverified external-service boundaries.

## Non-goals and Review Separation

- No runtime dependency additions, unrelated features, blanket assertions, lint suppressions, or changes to provider/DSH permissions.
- Author implementation and independent review are separate passes. Review results count only when a reviewer completes.
- Live provider credentials, real DSH file mutations, OneBot delivery, and signed installers are not validated by static checks or mocked tests.

## Results

### Confirmed fixes

- Bound `isRecording` into `ChatVoiceStatus`, so the recording indicator and stop-recording presentation follow the owning chat state.
- Removed the unused `set-dnd` emission path from `WorkspaceDrawer`; the component declares and emits only the supported mute event.
- Repaired renderer nullability, event, action, and runtime adapter contracts, with focused regression coverage for voice state, pet controls, chat-store actions, and VRM runtime behavior.
- Fixed confirmed backend issues found during the audit: secret redaction in LLM audit details; MCP subprocess cleanup when initialization is cancelled; SSE timeout isolation so one timed-out request does not cancel unrelated same-session work; and QQ Bridge process ownership/state retention when stop fails.
- Resolved the two remaining `basedpyright` composition-boundary errors. The config remains a writable protocol because runtime reload mutates it; the concrete application composition casts are limited to the known `AppConfig` and socket-server implementations. `SocketServiceInjector` uses `Any` for opaque service instances so its protocol accepts concrete typed implementations without claiming those services are arbitrary `object` values.
- Applied Ruff safe mechanical fixes and retained behavior-sensitive exception handling for later evidence-based review.

### Verification on 2026-11-03

- Full Python suite: `907 passed, 2 skipped`.
- Runtime-config and settings probe regression tests: `6 passed`.
- `basedpyright`: `0 errors, 0 warnings, 0 notes`.
- Electron `npm run type-check`: passed. Renderer gate reports 3 known diagnostics in 1 file, `0` new messages, and no files over the recorded baseline. This is a baseline gate, not a claim of zero renderer diagnostics.
- Ruff: `181` diagnostics remain, down from `862` (`681` fewer). The current total includes `95` BLE001 and `3` S110 findings; each remaining diagnostic still requires contextual review. Ruff findings are not equivalent to runtime defects.
- `git diff --check`: passed; Git emitted only existing CRLF-to-LF working-copy warnings.
- Ruff run against `python/app.py` plus `python/modules/system/runtime_config.py` reports 12 findings in `app.py`; these are existing broad-catch/global-scope diagnostics, not introduced by the typing-boundary change.

### Remaining limits

- Live provider credentials, real DSH file mutations, OneBot delivery, and signed installer behavior remain outside local automated verification.
- The 3 renderer diagnostics and 181 Ruff findings remain visible technical debt; their presence alone does not prove user-visible failures. No broad exception-handler rewrite was made solely to reduce lint counts.

## Follow-up: MCP Transport Lifecycle (2026-11-03)

### Confirmed defects and repairs

1. A closing SSE listener unconditionally removed the server registration, including a replacement session. Cleanup now removes only its own registered session, clears only its own telemetry session ID, and attributes closing/pending-failure history to the old session. Regression coverage includes current, detached, and replacement registrations.
2. Stdio shutdown bounded its graceful wait but waited indefinitely after `kill()`. Both exit waits now have a 3-second timeout; process-exit races are handled separately, and failed cleanup emits a redacted warning. This bounds the waits, not a guarantee that the operating system has reaped an unresponsive process.
3. SSE cancellation during HTTP dispatch left a pending registration; cancellation during result waiting left an unresolved shielded future. A shared `finally` now removes the request and settles its local future without cancelling unrelated requests. Dispatch failures and listener failures during dispatch are also covered.
4. SSE close suppressed caller cancellation along with the expected reader cancellation. It now propagates cancellation of the closing task while preserving ordinary reader shutdown behavior.
5. Independent review found the same ownership bug in legacy stdio: an old request removed the replacement registration on read failure or old-process exit. Both removals now check session identity. Six regressions cover the two failure paths across current, detached, and replacement registrations, including preservation of the replacement process.

### Evidence and verification

- Regression-first evidence: the old listener removed the replacement registration; shutdown exceeded its test deadline after kill; cancellation tests exposed the pending-registration and future leaks; cancelling the close task returned normally instead of raising `CancelledError`. The legacy stdio regression first reported `2 failed, 4 passed`, then passed after identity checks. Each corresponding regression passes after the repair.
- Lifecycle suite: `34 passed` in `python/tests/test_mcp_transport_lifecycle.py`, including initialization cancellation and timeout-isolation coverage added during the earlier investigation.
- Full Python suite after all five repairs: `931 passed, 2 skipped`.
- `basedpyright` after all five repairs: `0 errors, 0 warnings, 0 notes`.
- Ruff for the lifecycle test file: all checks passed. Ruff over `python scripts services`: `180` remaining diagnostics, including `93` BLE001 and `2` S110 findings. This is the current scoped total; the `181` above is the earlier checkpoint, not the latest count.
- The previously collected Electron type-check evidence remains applicable: 3 known renderer diagnostics, no new diagnostics. This follow-up changes no frontend files and does not resolve the missing Three.js declarations.
- Independent read-only review confirmed the SSE changes and identified the legacy stdio omission. A separate follow-up review confirmed its repair and independently ran the six new regressions: `6 passed, 28 deselected`; no further findings in that bounded review.
- Documentation validator: passed (`23` Markdown files). `git diff --check`: passed with only CRLF-to-LF working-copy warnings.

### Verification boundaries

- Tests exercise actual asyncio tasks and HTTPX mock transports, with controlled subprocess doubles. They do not verify live MCP servers, actual OS child termination under failure, provider credentials, DSH mutations, OneBot delivery, or signed installers.
- This follow-up edits the MCP manager, its lifecycle regression tests, and this report. Other existing worktree changes are preserved and are not attributed to this follow-up.
