# Native Desktop Actions

Yuizaki's native desktop beta is limited to visible top-level window discovery,
foreground focus, and graceful close requests. It never launches a shell,
starts or terminates a process, injects mouse/keyboard input, or exposes native
window handles, XIDs, PIDs, executable paths, or permission authority to the
renderer or model.

## Code evidence

- Platform adapters and the public controller are in
  `python/modules/agent/desktop_actions.py` (`WindowsDesktopActionAdapter`,
  `X11DesktopActionAdapter`, `SystemDesktopActionAdapter`, and
  `DesktopActionController`).
- Electron host routing and token forwarding are in
  `electron/src/main/desktop-action-bridge.ts`,
  `electron/src/main/http/routes/system-routes.ts`, and
  `electron/src/main/desktop-action-hotkey-coordinator.ts`.
- Agent registration and policy entry points are in
  `python/modules/agent/runtime.py`, `tool_registry.py`,
  `tool_executor.py`, and `permission_receipt.py`.
- Contract coverage is in `python/tests/test_desktop_action_contract.py`,
  `test_computer_use_host_control.py`, `test_native_desktop_beta_adversarial.py`,
  and the Electron `desktop-action-*` tests.

## Authority and lifecycle

- The feature starts disabled. The authenticated desktop host must explicitly
  enable or rearm it.
- `TurnService` binds every mapping, prebuilt, and streaming semantic turn to
  workspace, session, turn, request, generation, and interruption epoch using
  explicit service-owned identity fields. Caller-extensible `ctx.extra` data is
  never action authority.
- Discovery returns at most 100 bounded labels with random target leases. A
  lease lives for no more than 15 seconds and is valid for one live action.
  Each discovered target receives private host-secret HMAC application/window
  scope identities bound to its native fingerprint; those identities never
  expose the fingerprint or native identifier.
- Preview is pure and returns a digest bound to the target fingerprint, full
  turn and target scope, action, feature revision, stop epoch, revocation
  generation, and a bounded confirmation summary naming action/application/title.
- Focus and close run only through `ToolRegistry` -> `PolicyEngine` ->
  `ToolExecutor` -> context handler. Both require an interactive permission and
  a sealed execution permit. Graceful close is high risk and never accepts a
  remembered allow.
- Disable, rearm, revocation, expiry, scope changes, or emergency stop invalidate
  leases and active fences. Emergency stop latches the feature disabled; normal
  enable cannot bypass it and only explicit rearm clears the latch.
- Discovery and the complete revalidate/effect/postcheck transaction run on one
  serialized driver lane. Discovery timeout is `DA_ACTION_TIMEOUT`. A timeout
  after a possible effect is `DA_OUTCOME_UNKNOWN`, latches emergency stop, and
  is never reported as retryable success.

The host-only feature gate is available at `/api/desktop-actions/status`,
`enable`, `disable`, `rearm`, `heartbeat`, `discover`, `grant`, and
`emergency-stop`. Every route requires the separate
`YUIZAKI_HOST_DESKTOP_ACTION_TOKEN` through `Authorization: Bearer ...`. The
renderer/backend token is rejected and there is no token fallback.

Enable and rearm create a five-second safety lease. Electron main renews that
lease once per second only while the emergency-stop hotkey remains registered.
Heartbeat requests carry the current lease epoch; expiry or an epoch mismatch
fails closed, advances the revocation boundary, and invalidates application
grants and target leases. Disable, emergency stop, hotkey loss, heartbeat
failure, and host disposal stop renewal immediately. Electron retries a failed
stop request only a bounded number of times; the Python TTL is the final
fail-closed guarantee after a transport failure.

Changing global input bindings is a fenced transaction. Electron stops the
desktop-action lease before `PetShortcuts` unregisters the existing emergency
hotkey. If the stop cannot be confirmed after bounded retries, the binding
change is rejected and the existing shortcuts remain registered. A successful
rebind does not restore desktop actions; the user must explicitly rearm them.

Application authorization is also host-only. Electron main performs a bounded
discovery, shows the labels and titles in a native picker, and submits the
selected opaque application ID plus discovery revision to `grant`. The renderer
can request this native management flow and receive its closed status, but it
never receives host tokens, opaque application/window IDs, lease epochs,
discovery payloads, grant handles, preview authority, or execution methods.
Application grants expire automatically and are revoked by a feature revision,
lease expiry, disable, rearm, or emergency stop. `/preview` always returns
`DA_HOST_BINDING_REQUIRED`; HTTP callers cannot synthesize turn scope.

## Windows

Windows uses `ctypes` with `user32` only. Discovery is restricted to visible
top-level windows with non-empty bounded titles. Focus uses
`SetForegroundWindow` and verifies `GetForegroundWindow`. Close posts
`WM_CLOSE`, allowing the application to present its own save/confirmation UI,
then observes the window for a bounded interval. It never force-terminates the
owning process.

Windows may reject foreground activation under its focus-stealing rules. That
is reported as `DA_FOCUS_REJECTED` or `DA_POSTCONDITION_FAILED`, not bypassed.
Application identity uses a bounded process-image digest where Windows permits
the query. If the identity query is unavailable, the scope is conservatively
narrowed to that single process/window rather than merging unrelated windows.

## Linux

Linux support is intentionally limited to an explicit X11 session:

- `XDG_SESSION_TYPE=x11`
- a non-empty `DISPLAY`
- discoverable `libX11`

X11 application identity uses same-user, local-session `WM_CLASS` as a
best-effort identity signal, not as a cryptographic application identity.
Missing or malformed identity is conservatively narrowed to one window rather
than grouping unknown windows.

The adapter uses `ctypes`/`libX11` for bounded discovery, verified input focus,
and ICCCM `WM_DELETE_WINDOW`. Pure Wayland returns
`DA_WAYLAND_UNSUPPORTED`. Missing X11 prerequisites return
`DA_X11_UNAVAILABLE`. No `xdotool`, shell command, subprocess, compositor
extension, or accessibility bypass is used. XWayland is supported only when the
session is explicitly represented as X11; native Wayland windows remain outside
this beta contract.

## Known beta limits

- Window titles and toolkit class labels are display evidence, not stable app
  identities; an internal fingerprint plus immediate rediscovery protects
  against native identifier recycling.
- Applications may ignore graceful close, show a save dialog, or close after
  the bounded observation window. The result distinguishes `closed` from
  `still_open` without claiming termination.
- Focus is a window-level capability. Native keyboard and pointer injection
  remains unavailable by default in `ComputerUseController`; status reports
  `native_input_available: false` explicitly.
