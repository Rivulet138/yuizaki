# Dependency Integration (2026-11-03)

## Scope

Integrate Dependabot PRs #49-60 and #67-69 while preserving their commit
ancestry. No forced audit fix, advisory dismissal, or disabled validation gate
is used.

## Compatibility Changes

- TypeScript 7.0.2 runs through the explicit `typescript-native` alias;
  TypeScript 6 remains the compiler API for Vue and typescript-eslint. Package
  scripts do not depend on colliding npm compiler bin shims.
- Electron development requires Node.js `^22.18.0 || >=24.11.0`, including
  the Babel 8 dependency engine floor. CI covers both minimum LTS versions on
  Windows and Linux.
- Hugging Face Hub 2 no longer accepts `local_dir_use_symlinks`. SoulX
  downloads omit that keyword and retain the existing missing-file fallback.
- minimatch 11.0.4 fixes GHSA-g3hv-75wg-m249. asar 4.3.1, universal 3.0.6,
  and Jake 13.0.3 remove incompatible older minimatch consumers.
- glob 14.0.3 fixes GHSA-3g3m-2fjr-6pw4 for glob >=9 consumers. The legacy
  `temp` cleanup path reaches rimraf/glob 7 but deletes tracked directories by
  exact path; wildcard matching by this old glob/minimatch combination is not
  covered or claimed as compatible. Regression coverage exercises `temp`'s
  actual async and sync tracked-directory cleanup, including nested and hidden
  files.

The overrides should be revisited when upstream dependencies adopt patched
ranges. `electron/scripts/dependency-security.test.ts` checks real consumer behavior,
archive round trips, lint matching, actual temporary cleanup, and bounded execution
of upstream minimatch regression fixtures.

## Verification And Boundaries

- Clean Electron dependency installation and full npm audit: passed, zero
  vulnerabilities. The node-mcp audit also reports zero vulnerabilities.
- Python regression suite: 876 passed, 2 POSIX-only skips on Windows. The five
  SoulX download regressions use strict Hub signatures, without network model
  downloads. `pip check` passes.
- basedpyright 1.40.2: no errors or warnings for Python 3.11.
- Electron build, renderer bundle audit, ESLint, and runtime start preflight:
  passed. Focused tests exercise both TypeScript toolchains.
- Go launcher tests, node-mcp tests (11), and documentation/resource/Python
  lock checks: passed.

The renderer retains its existing type baseline (25 errors in 9 files); the
gate rejects new errors rather than pretending the baseline is clean.
Whole-repository Ruff is **not clean**: 0.17.3 reports 862 diagnostics versus
765 under the previous locked 0.16.9 on the same tree. Changed Python files
pass Ruff. No blanket ignore configuration or unrelated mass rewrite was
added. This corrects the earlier review report's erroneous zero-diagnostic
claim.

No real OpenLux request, authenticated DSH write task, OneBot bridge delivery,
model-weight download, or signed release installer was validated by these
dependency tests.
