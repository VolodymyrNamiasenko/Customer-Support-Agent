# Pilot instrumentation v1

This is a trusted-local, single-user workflow. The code/examples/fixtures are synthetic. No client documents, ratings, identities or production outcomes are committed. No automatic deployment, corpus tuning or remote publication of pilot data is provided.

Approved operator choices: SME role **Manufacturing Engineer** (self-reported, not authenticated); low satisfaction **1–2**, high **4–5**, neutral **3**; stable random high-rating inclusion probability **10%**. This is Bernoulli sampling per response, so small cohorts need not contain exactly 10%. Every flagged high-rating/guard-passed SAP-owned/read-only case is selected independently of the random draw. Question/context ownership signals also trigger selection if the generation guard missed them. These are heuristic signals, not complete entity-ownership verification; random review remains important.

## Data, identity and measurement

Customer satisfaction remains 1–5. `POST /api/reviews/{id}/rating` needs `version`, `rating`, optional `note`. The old `actor` input is accepted for compatibility but discarded: **no name, name hash, customer identifier, IP or identity mapping is stored by the rating code**. All new rating events use `anonymous_customer`. Do not enter identifying information in feedback. Questions, answers, comments and timing can themselves identify someone; they are not automatically de-identified. Reverse identification through contextual data is not prevented.

SME correctness is separate: `POST /api/reviews/{id}/expert-verdict` takes `version`, `correctness`, `error_bucket`, `rationale`, and nonempty `evidence` references. The recorded role is Manufacturing Engineer with `self_reported_role` assurance. The app does not verify qualifications or enforce separation of duties. Correctness is null until explicitly judged. A negative expert verdict revokes a prior release approval; a correct verdict does not automatically approve release. Rating never supplies a correctness label.

`GET /api/reviews/metrics` preserves old all-record counts for compatibility and adds `pilot`:

- `satisfaction`: latest rating per response, `mean_rating` and `N`.
- `expert_correctness`: latest explicit verdict per response, `N_reviewed`, counts of correct/partially_correct/incorrect, correct/N_reviewed and coverage. With no reviews the fraction is null, not 0%.

No combined score is calculated. A 5-star incorrect answer reports satisfaction 5/5, N=1 and expert correct 0/1. Risk-enriched expert sampling does **not** estimate unbiased whole-pilot accuracy. Denominators count responses, not unique people. Existing records are `legacy_unknown`, excluded from pilot metrics; their historical ratings are not relabelled as client feedback. Historical rating actor names are sanitized in API history/export, but the private original append-only DB is preserved unchanged.

The operator authorized storage with anonymous rating actors. The app records that basis, **not verified participant consent**. Before real collection, the operator must establish participant notices/consent where required, retention duration, access and withdrawal/deletion handling. Those legal/operational policies are not inferred from software approval. No automatic expiry or deletion service is implemented.

## Trace and audit

Every new attempt is persisted before retrieval. One Chroma query returns actual collection IDs, distances and ordered results before DSPy generation. Deduplication records discarded IDs and the selected context IDs. DSPy does not choose chunks.

Trace includes k, distance metric/direction, content hashes, corpus/index fingerprint including embeddings, observed model tag/digest, embedding model/revision and unresolved version fields. Distances are not probabilities. `used_context_chunk_ids` records input context selected for generation, **not proof of which facts the model used**. Claim-level usage remains `not_observed`. Guard replacement is recorded separately in the generation event/payload. Retrieval/generation failures leave an audit record; failed or unfinished attempts cannot be approved or rated. Unknown runtime versions remain null, with a reason, rather than a fabricated version.

`ReviewStore` uses additive/idempotent migration, expected response versions and transactions; stale writes return 409. Original events are not rewritten. New audit, trace, verdict, selection and evaluation tables have append-only update/delete triggers. This is not tamper-proof storage against an operator who controls SQLite/files/code. Back up the private DB before upgrading. Interrupted attempts remain visibly unfinished; an `applying` corpus change after a process crash requires operator recovery from backups/reconciliation, not blind retry.

`GET /api/reviews/expert-queue` returns unreviewed selected cases and reasons. `include_reviewed=true` exposes selection history after judgement. Selection is stable across refresh/restart; the stored seed, policy version, rating version and reasons are exported. A later customer rating does not erase a prior safety selection.

## Frozen retrieval evaluation

`evaluation/cases.json` remains the **six dev guard cases**. Separately frozen `evaluation/heldout/retrieval_v1.json` contains four new invented retrieval questions; `corpus_v1.json` has five relevant evidence chunks and two distractors. `manifest.json` pins both files by SHA-256. Tests check hashes, duplicates and normalized overlap; human scenario review is still required for semantic leakage. Do not tune on these questions or redefine gold labels after seeing failures. If used for tuning, create a new independently reviewed held-out version before a new final benchmark claim.

Recall is `|top_k ∩ gold_relevant| / |gold_relevant|`, macro-averaged over N questions. k=3 is frozen for v1. This tests retrieval, not customer satisfaction, generation correctness or production quality. The small synthetic benchmark cannot prove coverage of private client documentation. Tests with fake embeddings prove contracts/formula only. The explicit CLI uses the app's configured `all-mpnet-base-v2` and real Chroma.

From the repository root, with the backend stopped:

```bash
# New empty synthetic index only. Record baseline setup before/after, not a feedback improvement.
python -m evaluation.corpus_change --active-dir data/synthetic-index \
  --review-db data/reviews.sqlite3 --bootstrap-synthetic

# Evaluate an existing index; output must be a fresh filename.
python -m evaluation.retrieval_holdout --collection-path data/synthetic-index \
  --review-db data/reviews.sqlite3 --output /private/tmp/synthetic-retrieval-report.json
```

Point the backend's configured index at the intended evaluated collection when preparing a real local workflow. Do not assume the example CLI path changes `backend/config.py` automatically. Keep the same embedding/index configuration; changing it is a separate reviewed search change. No silent migration of indexes or replacement of a running collection occurs.

## Human-controlled corpus changes

The normal app enables pilot governance: upload/delete requires an evaluated `change_id`. Customer ratings only prioritize review; they cannot authorize a change. Workflow:

1. SME records a corrective verdict with evidence. The app never manufactures a real SME judgement.
2. Stop the backend and back up registry/uploads/index together. Stage a candidate in a **fresh** directory, using a private authorized file (the example below is invented).
3. Evaluate active and candidate with the same frozen fixture, k, embedding provenance and retrieval configuration. Both runs are stored. Gold labels are unchanged if a relevant source disappears.
4. A human proposes the exact file operation and reason. The proposal links the current SME verdict and both runs. Equal or worse recall is visible; the software does not silently report improvement or autonomously choose acceptance.
5. Start the app, inspect the plan, enter its ID in Documents, and explicitly upload/delete the exact evaluated file. The backend checks the before fingerprint, file hash, operation, current verdict and candidate after fingerprint. Mismatch rejects/rolls back and is audited. IDs are single-use; changed corpora/verdicts require new evidence.

```bash
python -m evaluation.corpus_change --active-dir data/synthetic-index \
  --candidate-dir data/candidate-unique --review-db data/reviews.sqlite3 \
  --upload examples/synthetic_support_guide.md --verdict-id 1 \
  --reason 'Human-reviewed synthetic corrective proposal'
# --delete filename.md stages a deletion instead of an upload.
```

The printed ID is a **proposal**, not an applied change. `POST /api/reviews/corpus-changes` can also register a plan from stored before/after run IDs. All applying/applied/failed events include the human actor and evidence links. API-created plans require a corrective expert verdict, never a rating. Initial synthetic setup is a separately named explicit bootstrap exception for an empty collection.

Search-configuration proposals can be journaled as `retrieval_config`; runtime model/index/code swaps are **not automatically applied** by this prototype. They require a controlled human maintenance step with corresponding evaluations and audit, not editing a live collection behind the app. Filesystem/code/DB access can bypass application controls; this is a single-user operating boundary, not enterprise authorization. A durable multi-store transaction/crash-safe index swap is not provided.

## Versioned private export

```bash
python -m evaluation.export_pilot --database data/reviews.sqlite3 \
  --output /private/tmp/pilot-export-unique.json
```

The CLI exports a single consistent SQLite read snapshot of records, review events with IDs/versions, traces, verdicts, queue selections, evaluation runs and corpus-change events. Schema v1 is `evaluation/pilot_export_v1.schema.json`; JSON Schema plus relational/denominator checks run before writing. A fresh owner-only file is required; overwrites and repository-contained targets are rejected. There is no new network export endpoint or automatic upload. Export may contain sensitive free text: store it privately and never commit it.

Checks: `python -m unittest discover -s tests -v`, `python -m evaluation.run_checks`, then `npm ci && npm run build` in frontend. Unit/mock success is not live Ollama acceptance or a real pilot outcome.
