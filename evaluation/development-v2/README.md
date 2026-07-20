# Synthetic-public development corpus v2

This directory is an independent, public development basket for semantic rules
`PRIN-004` through `PRIN-007`. It contains **48 new synthetic cases** and no
holdout split. Expected outcomes are intentionally visible: this data supports
development and regression work, but can never be release evidence.

The corpus does not import, reference, copy, materialize, or mutate
`evaluation/gigaagent`. Validation, materialization, fixture scoring, and tests
are offline and make no model or API calls. Live evaluation has a separate,
paid-guarded entry point described below.

## Coverage and semantic contracts

| Rule | Positive | Negative | Unresolved |
| --- | ---: | ---: | ---: |
| PRIN-004 | 6 | 4 | 0 |
| PRIN-005 | 6 | 4 | 0 |
| PRIN-006 | 6 | 8 | 3 |
| PRIN-007 | 14 | 4 | 1 |

The 24 reciprocal metamorphic pairs cover predicate flips, English/Russian
translations, same-meaning paraphrases, injection invariance, YAML/Markdown ADR
format invariance, a deterministic structural `SEAF-004` direction flip, and
completion controls for missing target, context, criticality, and status.
Compound cases include a `PRIN-005` + `PRIN-006` example and a paired near miss.
Weak and valid ADRs are represented in both structured and prose artifacts.

Dangerous controls have an explicit two-edge meaning. The reciprocal
metamorphic edge either flips the dangerous predicate directly, or preserves
the positive behavior for invariance testing. When it preserves the behavior,
a separate clean negative control must remove a rule-specific predicate. The
validator requires the control to be an approving metamorphic control, verifies
the rule-specific removal feature, and rejects a secondary control unless the
reciprocal pair is a semantic-preserving positive pair. Thus a case cannot name
an arbitrary nominal negative as its safety control.

The four incomplete/completion pairs are also integration-tested through the
actual `ReviewService.prepare_review` path, not merely against corpus labels:

- `dv2-041` / `dv2-042`: an absent/present integration target through native,
  trusted SEAF references;
- `dv2-043` / `dv2-044`: an absent/present referenced Markdown ADR;
- `dv2-045` / `dv2-046`: missing/present source criticality;
- `dv2-047` / `dv2-048`: missing/present target status.

For every pair, the incomplete case is rejected before review with the expected
unresolved preparation error, while its completed control is review-ready. The
integration test uses no model calls.

The paid boundary performs the same trusted host preparation before provider
preflight. Exactly the four locked incomplete cases are finalized fail-closed
by the actual `ReviewService` without starting an Ouroboros task or invoking an
MCP tool. Their captures retain a host attestation, the schema-validated service
final's attested hash and normalized projection, and explicit
zero-call/zero-token/zero-cost usage. Every other case must report the normal
model execution path, trusted receipts, and at least one model call. An all-48
regression exercises this exact `4` host / `44` model boundary offline. Every
case passes through verified trusted preparation; the ready cases then use
synthetic model envelopes, so the regression makes no provider call.

`dv2-041` also produces the deterministic structural finding `SEAF-001` while
its PRIN analysis is unavailable. That finding is explicitly locked as
`expected.auxiliary_findings`, preserved in the signed raw host attestation,
and checked during scoring and strict series re-scoring. It is removed only
from the normalized PRIN projection, so it cannot inflate or penalize the four
semantic-rule metrics.

## Offline commands

Run these commands from the repository root:

```bash
make validate-development-v2
make verify-development-v2
python3 evaluation/development-v2/corpus_tool.py hash
python3 evaluation/development-v2/corpus_tool.py materialize \
  --case dv2-008-duplicate-injection --output /tmp/dv2-case
python3 evaluation/development-v2/corpus_tool.py materialize \
  --all --output /tmp/dv2-all
```

The destination must not exist. Each case becomes an isolated Git repository
with deterministic base and head commits, a clean working tree, `dochub.yaml`,
the locked project extension, pinned `seaf-archtool-core` and SEAF-core gitlink
entries, and SEAF-native documents consumable by the verified trusted AGA
preparation path. Expected outcomes are deliberately **not** copied into
repositories supplied to the reviewer. Paths, JSON Pointers, evidence binding,
duplicate YAML keys, schemas, Git revisions, dependency pins, and unsafe writes
all fail closed.

`runner.py --score-fixture FILE` is the only fixture scorer. It accepts only an
explicit `mode: fixture` bundle, re-materializes the selected repositories,
binds every finding to a real head artifact and JSON Pointer, and always marks
the result non-release. Fixture files cannot claim series context. Trusted live
captures enter the scorer in memory through the paid runner; persisted captures
become trusted series inputs only after the attestation and re-scoring checks
described below.

The development gate requires, among its other thresholds, zero unsafe
approvals, zero invalid or hallucinated evidence records, and at least `0.85`
exact-case accuracy. `make verify-development-v2` tests these fail-closed
conditions without contacting a provider.

## Measurement identity and readiness

`measurement-config.yaml` is the canonical measurement contract. It fixes the
Ouroboros runtime version and source commit, OpenRouter provider, model, executed
prompt, live runner, reviewer skill, execution bundle, complete 48-case
selection, 900-second per-case timeout, five required repeats, isolated state
policy, and create-new output policy.

`corpus.lock.json` separately locks the corpus bytes, semantic ground truth,
validator, scorer, and paid runner. In `series_freeze.state: pre_measurement`,
the series identifier, timestamp, active measurement identity, and attestation
key identity are all null. Before any measurement, the owner must freeze a new
series and bind the lock to:

- runtime ID, version, and source commit;
- provider and model;
- hashes of the prompt, active configuration, live runner, reviewer skill, and
  execution bundle;
- the complete selection ID and ordered-selection hash; and
- an HMAC key ID and SHA-256 hash for a secret kept outside the repository.

The frozen mutation policy covers the corpus, ground truth, validator, scorer,
paid runner, prompt, configuration, model, and selection. Readiness validation
recomputes the active identity and fails if it differs from the frozen one.

Independent human review cannot be self-attested by automation. The checked-in
lock therefore truthfully records `independent_human_review.status: pending`.
An independent reviewer must inspect all expected outcomes, then record
`accepted`, their identity, and a UTC timestamp. Corrections require lock
regeneration before freezing a new series. The strict readiness gate is:

```bash
python3 evaluation/development-v2/corpus_tool.py validate --require-measurement-ready
```

Until that command passes, the corpus is valid for offline engineering use but
all live captures and series verification are blocked. The paid runner checks
explicit owner confirmation, the complete selection, repeat identity, accepted
human review, and the frozen series before importing live execution code or
making a model call.

To inspect a freshly computed pending-review lock without writing files:

```bash
python3 evaluation/development-v2/corpus_tool.py print-lock
```

## Capturing the five paid repeats

Provision the frozen HMAC secret as a regular, single-link file outside the
repository with restrictive permissions. Its SHA-256 must match the key hash in
the frozen lock. Never commit the secret. Then run the paid target once for each
ordinal `1` through `5`, using a distinct lowercase capture ID every time:

```bash
make evaluate-ouroboros-development-v2 \
  DEVELOPMENT_V2_PAID_APPROVED=yes \
  DEVELOPMENT_V2_REPEAT_ORDINAL=1 \
  DEVELOPMENT_V2_CAPTURE_ID=series-a-r1 \
  DEVELOPMENT_V2_ATTESTATION_KEY_FILE=/secure/outside-repo/development-v2.hmac
```

Repeat the command with ordinals `2`, `3`, `4`, and `5` and new capture IDs.
Each successful invocation covers all 48 cases. The default result path is:

```text
.aga-runs/development-v2/captures/<series-id>/repeat-<ordinal>-<capture-id>.json
```

The series ID, repeat ordinal, capture ID, and case ID are part of each
idempotency key. Before the first model call, the runner atomically reserves an
ordinal ledger at
`.aga-runs/development-v2/live-state/<series-id>/repeat-<ordinal>/`, writes a
signed attempt marker, and creates a new empty state directory there. An
existing ordinal ledger blocks retry even when a different capture ID is used.
A live response is rejected if it reports cache reuse, and task and review
identities must be unique within the capture.

Capture output is create-new and written atomically: an existing destination is
never overwritten. A completed, signed capture is persisted before its quality
gate is checked, so a gate-failing repeat remains available for worst-case and
flapping analysis; it is still non-release and cannot qualify the series.
Failures before a complete scored capture do not fabricate a result file.
They do leave a signed, non-release terminal failure record in the ordinal
ledger, containing only the stable failure code and completed-case count. This
retains failed attempts for selection-bias audit without storing raw errors or
secrets. Both state and capture output paths are restricted to their canonical
`.aga-runs/development-v2` locations; direct CLI paths cannot target source or
Git metadata.

With the checked-in pending human review, the paid command intentionally stops
before the profile manager, provider configuration, or any model call.

## Verifying the series

After all five distinct capture files exist, provide exactly those five paths,
owner-supplied per-repeat latency and cost caps, and the same external HMAC key:

```bash
make verify-development-v2-series \
  DEVELOPMENT_V2_SERIES_INPUTS="\
.aga-runs/development-v2/captures/series-a/repeat-01-series-a-r1.json \
.aga-runs/development-v2/captures/series-a/repeat-02-series-a-r2.json \
.aga-runs/development-v2/captures/series-a/repeat-03-series-a-r3.json \
.aga-runs/development-v2/captures/series-a/repeat-04-series-a-r4.json \
.aga-runs/development-v2/captures/series-a/repeat-05-series-a-r5.json" \
  DEVELOPMENT_V2_MAX_P95_MS=120000 \
  DEVELOPMENT_V2_MAX_COST_USD=10.00 \
  DEVELOPMENT_V2_ATTESTATION_KEY_FILE=/secure/outside-repo/development-v2.hmac
```

The verifier requires ordinals exactly `1..5`, distinct input paths, capture
IDs, signed-attempt marker hashes, timestamps, and capture-set hashes, and an exact match to the frozen
series, identity, lock hashes, and ordered 48-case selection. It authenticates
every complete result with HMAC-SHA256 before treating the file as trusted; a
JSON file cannot self-label itself as trusted without the external secret.

Stored metrics and gate decisions are never accepted on faith. The verifier
reconstructs every response from the retained raw/normalized output and Git
revisions, runs the strict scorer again for all five captures, and rejects any
difference in runs, metrics, gate results, or capture hash. Qualification uses
the worst quality value across repeats, requires every recomputed gate to pass,
applies the latency and cost caps to every repeat rather than only to pooled
averages, and rejects any case that flips between approve and non-approve.

Trusted scoring and re-scoring independently revalidate the raw execution
boundary as well: the four locked incomplete cases require the attested
zero-model host path, while the other 44 require correlated prepare/finalize
receipts and complete nonzero-call model accounting. Any execution, receipt,
usage, or auxiliary-attestation mismatch increments the zero-tolerance invalid
evidence metric, so the gate cannot pass on normalized answers alone.

The series report includes per-repeat and pooled latency, worst-repeat quality,
summed prompt and completion tokens, unknown-token counters, known cost, and
unknown-cost counters. Prompt-token, completion-token, and cost accounting must
all be complete, and every repeat must stay under the supplied cost cap. A
complete but non-qualifying series remains non-release and the verifier exits
nonzero.

This corpus is not a holdout and never provides release metrics. A closed
holdout must be created and frozen through a separate release process.
