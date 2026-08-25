# Long-term memory / 长期记忆

Status: active architecture baseline, refreshed 2026-08-17.

## Goal

Yuizaki's memory is a local, inspectable relationship record. SQLite is the
authority. Embeddings, rerankers, summaries, and optional Qdrant collections
are projections that can be rebuilt from the authority.

The implementation follows four rules:

1. Events are evidence; derived memories are versioned interpretations.
2. Retrieval is scoped, time-aware, and explainable.
3. Corrections retain history and immutable origin provenance.
4. Forgetting is immediately enforced at every recall boundary; permanent
   deletion is explicit and propagates to configured projections.

## Evidence policy

This design combines patterns instead of adopting another memory framework as
the authority. Sources were reviewed through 2026-08-14 and are labelled by
what they can establish:

| Level | Meaning | Claim boundary |
| --- | --- | --- |
| Local | Yuizaki tests or measurements against the checked-out implementation | Can establish repository behavior for the tested cases only |
| E1 | Public benchmark assets, paper, or an official upstream release | Supports task definitions, interfaces, and an upstream version fact; it does not establish a gain in Yuizaki |
| E2 | Architecture paper or project-authored evaluation | Supports a design hypothesis; reported quality, latency, and cost remain system- and model-specific |
| E3 | 2026 arXiv preprint without independent local reproduction | Directional evidence only; it cannot be treated as a production guarantee or a reason to add a dependency by itself |

Local evidence is the acceptance authority. A newer paper is not stronger than
a failing lifecycle, isolation, or rollback regression test.

## Papers and comparable projects

The canonical source list, evidence levels, 2026 research watch items, upstream
snapshots, and exact Yuizaki implications are maintained in
[REFERENCES.md](REFERENCES.md). No listed project is a runtime dependency.
SQLite remains the local authority; embeddings and the optional vector index
remain rebuildable projections.

## Adopted and deferred

This iteration adopts four bounded changes:

1. **Bounded version history and rollback.** Every edit retains a capped audit
   history. Rolling back to a selected revision creates a new revision and
   preserves the intervening revisions; it never rewrites origin provenance.
2. **Explicit time semantics.** Event time, update time, validity windows, and
   expiry are distinct. Recency prefers `occurred_at`, then `updated_at`, then
   the legacy `timestamp`; comparisons normalize timezone-aware UTC values.
3. **Explainable score components.** Query results expose semantic, lexical,
   recency, quality, optional learned-reranker, and final scores so the panel
   can explain ordering without exposing memory text to external telemetry.
4. **A local evaluation baseline.** Golden cases measure Recall@K, MRR,
   lifecycle and scope leakage, candidate/filter counts, retrieval latency,
   token cost, evidence coverage, and Write/Execute/Forget/Repair security-phase pass rates. A
   security phase passes only when expected safe evidence is retrieved (or
   abstained from) and forbidden/lifecycle-leaked evidence is absent.

The following work is deliberately deferred:

- **Graph dependency.** Add one only if local multi-hop cases show a repeatable
  gain over lexical/semantic hybrid retrieval large enough to justify another
  storage, migration, backup, and deletion surface.
- **Automatic LLM consolidation.** Define evidence-preserving segments,
  provenance authority, failure handling, and cost budgets before enabling it.
- **Automatic conflict merge.** Conflicting memories remain reviewable. Do not
  silently merge or revoke them until deterministic policies and regression
  cases cover false conflicts and later corrections.
- **Cloud memory service.** Local SQLite ownership, privacy, offline operation,
  and deterministic erasure remain product requirements; no external memory
  authority is introduced.

## Data model

A canonical document has a stable `id`, user-visible `text`, and versioned
metadata. Unknown metadata fields are preserved for forward compatibility.

Required normalized metadata includes:

- `schema_version` and `revision`
- `created_at`, `updated_at`, `occurred_at`, and `ingested_at`
- `layer`, `scope`, `workspace_id`, and optional `session_id`
- `type`, `importance`, `confidence`, `quality_score`, and `review_status`
- immutable `event_kind`, `source_kind`, `source_id`, `source_ids`, `turn_id`, and `evidence`
- `trust_level` (`trusted`, `verified`, or `untrusted`), `sensitivity`/`sensitive_category`,
  and the auditable `admission_policy`/`admission_reason`
- `valid_from`, optional `valid_to`, `supersedes`, and `superseded_by`
- bounded `version_history`, `confidence_history`, `correction_history`, and `audit`

The lifecycle state is derived from canonical metadata. It is not a second
mutable authority:

```text
rejected | forgotten | invalid | expired | scheduled | superseded | active
```

`forgotten`, `invalid`, `expired`, `superseded`, and `rejected` records cannot cross the
final retrieval boundary. A soft-forgotten record can be restored; a
permanently deleted record cannot.

Candidate admission is fail-closed. Unknown sensitivity or trust values are
rejected instead of being coerced. Candidates remain `pending` unless the
writer explicitly requests `low_risk` admission and all gates hold:
`sensitivity == none`, trust is `verified` or `trusted`, and the source is a
local builtin/runtime source. Web, OCR, MCP, and plugin evidence remains
`untrusted` and requires review. Tool provenance is stored separately from the
semantic `event_kind`, so a successful tool event cannot erase its origin.

## Write and correction flow

```text
source event
  -> scope and layer routing
  -> provenance and quality normalization
  -> duplicate/conflict candidate search
  -> canonical write or review response
  -> rebuildable index update
```

Manual correction increments `revision` and appends the previous text and
relevant metadata to bounded version history. Origin provenance remains
immutable. A future extraction pipeline may create new records linked through
`supersedes`, but it must not rewrite raw events.

## Recall flow

```text
query + scope + layer policy
  -> recallability filter
  -> semantic and lexical candidate union
  -> optional learned reranker
  -> recency + quality weighting
  -> final recallability boundary
  -> token-bounded selected memories + trace
```

The trace is product data for local diagnostics. It includes the selected IDs,
candidate and filtered counts, rejection reasons, latency, ranking strategy,
and score weights. It does not require exporting memory text.

## API surface

The renderer should use the canonical `/memory` surface:

| Endpoint | Purpose |
| --- | --- |
| `GET /memory/docs` | List scoped documents, optionally including forgotten history |
| `GET /memory/overview` | State/layer/source counts, review queue summary, recent activity, index health |
| `POST /memory/memory/add` | Add a routed typed memory with duplicate detection |
| `PUT /memory/docs/{id}` | Versioned edit/correction |
| `POST /memory/docs/{id}/rollback` | Restore a selected historical revision as a new revision |
| `POST /memory/docs/{id}/soft-forget` | Stop recall without destroying history |
| `POST /memory/docs/{id}/restore` | Restore a soft-forgotten record |
| `DELETE /memory/docs/{id}` | Permanent deletion with reference cleanup |
| `POST /memory/query` | Canonical layered query and retrieval trace |
| `POST /memory/maintenance/preview` | Deterministic scoped deletion impact preview |
| `POST /memory/maintenance/apply` | Confirmed permanent maintenance purge |

Legacy RAG and pipeline query routes remain compatibility adapters. New UI code
must not add another query protocol.

## Panel contract

The default memory panel is for understanding and correcting the companion's
current memory. It is not an index administration dashboard.

- Library: quick capture, natural-language search, human-readable categories,
  master-detail editing, validity/expiry controls, provenance, and rollbackable
  history.
- Review: inferred, low-confidence, duplicate, conflicting, or stale items.
- Overview: current recallable memory, protected/core categories, recent
  activity, and review count.
- Advanced drawer: recall lab, per-result score components, trace, raw document
  write, maintenance preview, and index diagnostics.

Backend selection, embedding models, reranker settings, and index rebuild stay
under Settings. Persona/heartbeat behavior debugging is labelled separately as
Behavior Runtime.

## Evaluation strategy

External benchmarks define capabilities and scenario shapes. They are not
product acceptance tests because Yuizaki has different data, privacy, scope,
models, and latency constraints. The release gate is a deterministic local
golden set with explicit source documents and relevant document IDs.

### Golden-case target matrix

The local set is expanded toward these cases:

1. lexical exact match that semantic retrieval ranks weakly;
2. semantic paraphrase without a useful exact token match;
3. multi-record evidence where each required document ID is labelled;
4. event time, update time, validity start/end, expiry, and timezone offsets;
5. correction, supersession, bounded history, and rollback to an older revision;
6. `forgotten`, `expired`, `superseded`, and `rejected` lifecycle exclusions;
7. workspace and session isolation, including identical text across scopes;
8. permanent deletion followed by index rebuild, proving non-revival;
9. missing evidence, where retrieval returns no supporting memory and the
   consumer must abstain;
10. immutable provenance across edit, soft forget, restore, and rollback.

Run lexical-only, semantic-only, and hybrid configurations over the same cases.
This makes the contribution of the hybrid union visible and prevents a graph or
reranker proposal from being compared against an artificially weak baseline.

### Metrics and trace fields

For each query, store the expected relevant IDs and collect:

| Dimension | Measurement | Interpretation |
| --- | --- | --- |
| Retrieval quality | Recall@1, Recall@3, Recall@5 | Mean fraction of labelled relevant IDs present in the top K |
| First useful result | MRR | Mean reciprocal rank of the first labelled relevant ID; a miss contributes zero |
| Evidence quality | Required evidence coverage pass rate | For cases with `required_evidence_ids`, the query trace must expose every labelled supporting ID; this is reported separately from answer/document recall |
| Lifecycle safety | Lifecycle leakage count | Any forgotten, expired, superseded, rejected, or permanently deleted result is a failure; the required value is zero |
| Scope safety | Workspace/session leakage count | Any result outside the requested scope is a failure; the required value is zero |
| Time correctness | Validity and recency case pass rate | Confirms UTC normalization, validity windows, expiry, and the documented recency fallback order |
| Explainability | Score-component completeness | Every returned result includes semantic, lexical, recency, quality, learned, and final components, using an explicit null/zero when a component does not apply |
| Work performed | Candidate, filtered, and returned counts | Detects quality changes hidden by unbounded candidate growth and identifies final-boundary filtering |
| Latency | Per-query elapsed time plus warm-run p50/p95 | Compared on the same machine and backend; cross-machine numbers are not treated as regressions |
| LLM cost, when applicable | Input/output tokens and service calls | Reported beside accuracy and latency; a path without an LLM records zero calls rather than an estimate |

The initial checked-in run establishes the local baseline. Later retrieval
changes must preserve zero leakage and non-revival invariants, then demonstrate
their Recall@K/MRR and latency delta against that baseline. Quality gains do not
waive lifecycle failures, and faster retrieval does not waive missing evidence.

### Reporting boundary

- Report retrieval quality separately from downstream answer quality. A reader
  model can hide retrieval misses or fabricate a correct-looking answer.
- Report evidence coverage separately from document recall. A query may retrieve
  the expected answer record while omitting one of the labelled supporting
  events; `required_evidence_ids` and trace `evidence_ids` make that gap
  measurable without exporting memory text.
- Keep raw memory text out of external telemetry. IDs, counts, filter reasons,
  weights, score components, and timing are sufficient for default diagnostics.
- Treat benchmark and paper numbers as the authors' results. Claim a Yuizaki
  improvement only after reproducing it with the local corpus, fixed settings,
  and recorded before/after measurements.
- Run LoCoMo, LongMemEval, LongMemEval-V2, or MemoryAgentBench as optional
  research evaluations. Their model and hardware requirements do not block a
  local desktop release.

Additional product limits remain unchanged: automatic reflection must stay
bounded and derived; sensitive-category auto-approval requires an explicit
privacy policy; backup erasure claims require documented user-managed backup
semantics.

Remote product metrics remain opt-in. When enabled, the HTTPS transport may
require schema-versioned export and deletion receipts matching the deterministic
batch idempotency key. An export receipt must also confirm the exact event
count; a missing or mismatched receipt fails closed. The request identity follows
the retry-safety direction of the IETF HTTPAPI `Idempotency-Key` draft, while
the receipt is Yuizaki's stricter application-level acknowledgement. This local
protocol does not prove that a production server is deployed or that deletion
has propagated across devices.

D7 retention uses an explicit observation cutoff. A user enters the denominator
only when their first active day plus seven days is not later than that cutoff;
newer users are reported as `excluded_immature_users` instead of being counted
as failures. Events after the cutoff are excluded and counted separately. This
follows the interval/cohort framing in the Mixpanel and Amplitude retention
documentation indexed in `REFERENCES.md`; it does not establish an online
Yuizaki retention result.
