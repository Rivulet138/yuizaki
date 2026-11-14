# R5 save performance acceptance - final-credential-build PASS

**Current acceptance evidence: `final-credential-build/results.json`. All four existing R5 performance scenarios passed on the build supplied after the credential recovery fix.**
`final-build` and all `current-dist*` runs are historical evidence only; they are not the current build acceptance.
Run: 2026-11-11T14:51:57.467155+08:00 to 2026-11-11T14:52:42.904382+08:00.
Captured build assets: `MemoryPanel-DYfQHE_M.js`, `SettingsPanel-MC9DEKgG.js`.
Renderer fingerprint was unchanged before and after this run. Fixture was closed; port 48949 was verified closed again after completion.

Executed command:

```powershell
python docs/fix-evidence-2026-11-11/panel-lifecycle/save-performance/measure_save.py --label final-credential-build
```

Primary files: `final-credential-build/results.json`, `final-credential-build/token-access-summary.json`,
`final-credential-build/token-pending-at-summary-ready.json`, `final-credential-build/save-normalized.json`,
`final-credential-build/save-legacy.json`, `final-credential-build/dist-before.json`, `final-credential-build/dist-after.json`.
Screenshots and DOM reconnaissance are in the same directory; console output is in `final-credential-build.log`.

The existing scripts were run without changes or extra scenarios. The runner owns its fixture subprocess on port 48949 and terminates it in finally. It never starts a real backend.
No old evidence or application source was edited.

## Browser path and assertions

- DOM reconnaissance first visits summary and waits for networkidle. Direct summary starts zero token GETs.
- Token case enters access through the application router. SettingsPanel refreshActiveSection calls refreshBackendTokenStatus and settingsClient.backendTokenStatus.
- Wait for the actual frontend GET to reach the host; click the rendered summary navigation tab; assert the hydrated field is visible, enabled, editable and focused while host token_started=1, token_pending=true, token_completed=0, and no browser requestfinished exists.
- Click access again while the same request is pending (deduplicated). Release only the synthetic response gate through a separate Python fixture-control request. Assert one browser requestfinished and the rendered R5_fixture_preview status.
- No page evaluation or init script calls fetch. CDP records the token request script initiator. Pending and completed screenshots, browser events and host HTTP records are retained.
- Normalized and legacy saves use separate clean contexts, summary only, and change trigger_messages from 24 to 25. Assert exactly one PATCH with that payload; zero/one additional settings GET respectively; saved UI; 1100ms duplicate observation plus networkidle.

## Current build actual counts

| Case | settings GET total | settings PATCH | token GET | Save readbacks |
| --- | ---: | ---: | ---: | ---: |
| discovery | 2 | 0 | 0 | n/a |
| token-access-summary | 2 | 0 | 1 | n/a |
| save-normalized | 2 | 1 | 0 | 0 |
| save-legacy | 3 | 1 | 0 | 1 |

There are two initial settings reads per context (application bootstrap and panel). Readback counts are measured after that baseline, not from total GET count.

## Timing and scope

- Token GET start to summary ready: 314.89ms; first settings GET to ready: 1070.25ms; held request duration: 890.96ms; release to token preview: 21.68ms.
- Normalized: edit to PATCH 976.85ms; edit to saved UI 1432.32ms.
- Legacy: edit to PATCH 957.69ms; edit to saved UI 1982.39ms.
- These are single samples with 150ms synthetic settings GET and PATCH latency. The token gate proves concurrency and completion, not a production latency budget.
- All cases have zero pageerrors. Browser console contains expected 404/409 and unavailable socket messages from deliberately incomplete fixtures and rejected background writes. This is not a console-clean acceptance claim.
- Browser attempts to mutate pet, workspace and voice diagnostics state were intercepted with 409. Only synthetic settings PATCH reaches the host; host validates its exact summary field and bounds. No non-fixture network destination was allowed.
- Renderer fingerprint: `2ac99cd4565feabef3559ccc359c7cc802953938fb7d88abef0770a216eccc35`; unchanged during this run.
- Fixture PID 38888 was terminated by the runner; port_closed=True. Exit code 1 is Windows subprocess.terminate(), not a test failure.
- This verifies the four R5 performance scenarios against the built browser renderer and synthetic HTTP only. It does not rerun credential DELETE recovery tests or verify Electron IPC or a real backend.

## Historical runs

- `final-build`: previous build pass, before the credential recovery fix; superseded by `final-credential-build`.
- `current-dist-v3`: pre-final-build pass; historical only.
- `current-dist-v2`: failed harness assertion exposed that browser request-start can precede host receipt. The script now waits for host receipt before checking pending at readiness; not a product regression.
- `current-dist`: invalid fixture-origin configuration rejected localhost after application normalization; not acceptance evidence.
