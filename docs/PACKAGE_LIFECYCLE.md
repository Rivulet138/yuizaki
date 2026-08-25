# Package lifecycle contract

The Electron main-process `PackageLifecycle` state machine is the authority for
capability-based package transitions. It is intentionally injected with an
artifact store and signature verifier so tests can prove the security and
rollback contract without writing to a user's profile.

Every package manifest carries a package id, version, SHA-256 digest, signing
key id, signature, capabilities, and optional runtime bounds. Installation is
accepted only when the digest, signature, runtime range, and capability allowlist
all pass. Updates require a strictly newer version and retain one rollback
version. Rollback fails closed if the previous artifact is missing or revoked.

Revocation removes an active version and prevents reinstalling that exact
version. Uninstall removes package artifacts while preserving user data by
default; callers must explicitly opt into a destructive data removal policy.
The lifecycle contract does not silently choose a key, download arbitrary
artifacts, or grant capabilities to a package. `TrustedPackageKeyAuthority`
provides the Ed25519 verification primitive for an explicitly injected key set;
`RotatingPackageKeyAuthority` accepts only root-signed, monotonic key-set
envelopes. The main process currently injects an empty authority, so it remains
fail-closed. `PackageLifecycle.install()` also removes a newly staged artifact
when its injected post-install health check fails. A production adapter must
still supply an authenticated key rotation source, download policy, OS
installer signing/notarization, and a real health check before exposing those
operations to users.

This separation follows the root/target and rollback concerns in the [TUF
security model](https://theupdateframework.io/security/) and its
[specification](https://theupdateframework.github.io/specification/latest/).
[Sigstore](https://docs.sigstore.dev/) is a complementary release-evidence
reference; neither external system is currently integrated into Yuizaki.

`PackageDistributionAdapter` and `HttpPackageArtifactSource` define the
download boundary without opening a user-facing route: HTTPS is mandatory,
origins are allowlisted, `content-length` and actual bytes are bounded, and
`AbortSignal` cancellation is honored before and after the request. Downloaded
bytes still pass through `PackageLifecycle` checksum, signature, and health
validation. The main process does not instantiate this network source until a
reviewed resolver and trusted key source are available. The current build
therefore proves the download and rollback boundary only; it does not prove
publisher identity, release signing/notarization, or a production update
service.

`HttpPackageKeyRotationSource` applies the same HTTPS/origin/size/cancellation
policy to root-signed key-set metadata. `PackageDistributionAdapter` only
passes the decoded envelope to an injected `PackageKeyRotationApplier`; the
authority, not the transport source, verifies the root signature and monotonic
version before changing keys. This is a tested release-runner boundary. No
remote endpoint, publisher identity, transparency log, or user-facing refresh
operation is enabled in the Electron main process.

The Electron main process now constructs `JsonPackageStateStore` and
`LocalPackageArtifactStore` below `app.getPath('userData')` during `createApp`.
Artifacts are stored as `packages/artifacts/<packageId>/<version>/artifact.bin`.
The adapter rejects path traversal and symlink escapes, writes with a temporary
file plus `fsync` and atomic rename, and never handles downloads or IPC itself.
The lifecycle instance is deliberately fail-closed through an empty
`TrustedPackageKeyAuthority` and a rejecting health check until trusted package
and runtime sources are supplied. This wiring proves the storage, signature
primitive, rollback cleanup, and restart state paths only; it is not a
production package distribution or installation feature.

`PackageLifecycle` accepts an injected `PackageStateStore` for durable
`activeVersion`, `previousVersion`, and `revokedVersions` state. State is saved
after every transition and removed on uninstall; a newly created lifecycle can
therefore restore revocation state before accepting an install. The adapter is
responsible for atomic persistence and corruption recovery. If durable state
save fails during install, the in-memory transition is rolled back and the
newly staged artifact is removed; the in-memory mode remains available for
isolated contract tests only.

The lifecycle also exposes read-only `reconcile()` and `reconcileAll()`
reports. `JsonPackageStateStore.listPackageIds()` provides a stable package
inventory; the Electron main process runs reconciliation during startup and
records a runtime diagnostic for corrupt state files or missing active/previous
artifacts. Reconciliation never repairs, deletes, or promotes a package, and
mutating operations remain fail-closed when an artifact reference is
unavailable.

Before an update or rollback, the lifecycle now verifies that every restored
`activeVersion` and `previousVersion` has a corresponding artifact. A missing
artifact makes the operation fail closed instead of allowing a new update to
silently sever the rollback chain. Revoke and uninstall remain available so a
caller can clean up a damaged or revoked state without restoring user data.
The lifecycle also validates the state shape returned by any injected
`PackageStateStore` at runtime; compile-time TypeScript types are not treated as
durable-data validation.

`RotatingPackageKeyAuthority` can now accept a `PackageKeyRotationStore`.
`JsonPackageKeyRotationStore` persists the last root-signed key-set envelope
with the same temporary-file, `fsync`, and atomic-rename discipline as package
state. A new authority verifies the persisted envelope against the injected
root key before restoring it; corrupt state, invalid keys, version rollback, or
a failed durable save leave the active key set unchanged. The Electron main
process still supplies no root key and therefore remains fail-closed; this
store is a release-runner building block, not evidence of publisher identity or
an operational update service.

`package-release-evidence.ts` defines the local release-runner boundary for a
post-install health check. `parsePackageReleaseEvidence()` applies a strict
allowlist and validates package identity, semantic runtime versions, SHA-256,
unique check names, and check statuses. `PackageReleaseHealthCheckRunner`
re-checks the artifact digest and required checks before returning a boolean
compatible with `PackageLifecycle`.

`LocalPackageReleaseEvidenceStore` is the read-only filesystem adapter for a
release runner's evidence directory. It resolves only
`<root>/<packageId>/<version>/evidence.json`, validates real paths and regular
files, rejects traversal and symlinks, and returns `null` for missing or
corrupt or oversized input so the health checker fails closed (the default
evidence file limit is 256 KiB). It does not write evidence,
verify publisher identity, or open an install/update route. A deployment may
inject `store.asResolver()` into the health checker after its authenticated
release job has produced the file.

The same module also defines an optional attestation envelope containing a
publisher identity, signer key id, and signature. `evaluateAttested()` and
`createAttestedHealthChecker()` first re-run the manifest/artifact checks and
then call an injected `PackageReleaseAttestationVerifier` over the canonical
manifest-plus-attestation payload. Missing, malformed, or rejected attestation
fails closed. This is only an authority boundary: no publisher key, identity
provider, transparency log, or production release runner is present here.

The runner accepts `local_contract` and `release_runner` evidence by default;
`real_device` is rejected unless a caller explicitly supplies that evidence kind
to the runner. This prevents a fixture or hand-edited JSON file from being
counted as Windows/Linux hardware qualification. The runner is a reusable
contract only: the Electron main process still injects a rejecting health check
and exposes no installation IPC. A release system must provide authenticated
evidence, publisher identity, OS signing/notarization, and the actual target
machine execution before enabling it.

Evidence:

- `electron/src/main/package-lifecycle.ts`
- `electron/src/main/package-trust.ts`
- `electron/src/main/package-distribution.ts`
- `electron/src/main/package-artifact-store.ts`
- `electron/src/main/package-state-store.ts`
- `electron/src/main/package-trust-store.ts`
- `electron/src/main/package-release-evidence.ts`
- `electron/src/main/index.ts` (`createApp` initialization)
- `electron/src/main/__tests__/package-lifecycle.test.ts`
- `electron/src/main/__tests__/package-trust.test.ts`
- `electron/src/main/__tests__/package-distribution.test.ts`
- `electron/src/main/__tests__/package-release-evidence.test.ts`
- `python/modules/agent/plugin_trust.py` for the existing Python plugin
  checksum/signature primitive.
