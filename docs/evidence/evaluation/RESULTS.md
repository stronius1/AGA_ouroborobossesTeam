# GigaAgent synthetic SEAF basket

## Status and measurement boundary

The independent basket contains 16 synthetic-public SEAF-native changes: eight
development and eight frozen holdout cases. Every case is materialized as an
isolated temporary Git repository with an actual base commit, head commit and
non-empty diff. Both revisions load through the project SEAF-native adapter.
This denominator is independent from the deterministic regression corpus.

**Real status: not run.** `evaluation/gigaagent/results.json` remains a zero-
denominator `mode: real` record because the official GigaAgent runtime contract
and permitted credentials are not available locally. No network call was made.

The recorded local run is explicitly a synthetic fixture measurement:

- input: `evaluation/gigaagent/fixtures/sanitized-response-bundle.json`;
- output: `evaluation/gigaagent/fixture-results.json`;
- status: `fixture_scored_non_release`;
- `release_evidence: false`, `release_eligible: false`, `release_passed: false`.

The CLI prevents fixture mode from writing the real `results.json`. Real-mode
scoring and writes are currently rejected as unsupported/unconfigured: without
an organiser-defined capture contract and a verified adapter, runtime/model
labels and oracle-shaped normalized output cannot establish official
provenance. Passing a bundle whose embedded mode does not equal the explicit
CLI mode is also an error.

## Frozen ground truth and structural correction

The initial case inputs omitted the mandatory `aga.project/v1` component
fields and did not materialize the endpoints of one integration. The inputs
were minimally completed with synthetic `owner`, `criticality` and
`target_status` values, the missing synthetic endpoints, and a frozen project-
extension document. No `labels`, expected status, verdict, finding rule,
severity, artifact or evidence matcher was changed. Before any real run, the
eight positive expected findings were additionally strengthened with exact,
resolving JSON Pointer locations taken from the reviewed synthetic fixture
anchors. This new field prevents a finding on the right artifact but the wrong
entity from matching ground truth; it does not change the expected outcome.

The corpus lock was therefore updated honestly:

- corpus SHA-256 after SEAF-native structural completion and anchor freezing:
  `df2d16746342fe71dedadb04252bfdec9c670a2bed65fe001b784bba15bba951`;
- independent labels/expected ground-truth SHA-256:
  `80d465f0b01dff5acad92946b99d7009da987da7eeeb97df01f569415d33ad01`.

`runner.py --verify-only` rejects any later change to the second hash. The
holdout remains marked `holdout_tuning_forbidden: true`.

## Basket balance

All PRIN-004..PRIN-007 rules have positive and negative cases. The basket also
contains five clean cases, two blocker cases, six major-labelled cases, three
near-misses, one prompt-injection artifact, one missing-context/incomplete case
and one multi-finding case. Both development and holdout contain an expected
blocker, so blocker recall has a non-zero denominator in each split.
The trusted catalog assigns PRIN-004, PRIN-005 and PRIN-007 `major` and
PRIN-006 `blocker`; the basket does not invent a `minor` downgrade merely to
add a severity label. Clean near-misses and the explicit incomplete outcome
exercise the non-finding and fail-closed sides of the scale.

## Strict offline scorer

The fixture runner accepts only an already captured UTF-8 JSON bundle. It never
invokes a model, API or adapter. The bundle must contain runtime/model names and
versions, prompt/config hashes, the frozen corpus hash, a redaction note, and
exactly one response for every materialized base/head SHA.

For each case the result retains:

- sanitized raw response;
- strict normalized output;
- schema errors;
- evidence checks;
- TP, FP and FN details;
- `PASS`/`FAIL` and a concrete reason;
- latency and actual base/head revisions.

A normalized finding has exactly `rule_id`, `severity`, `confidence`,
`artifact`, `location`, `evidence`, `source_ref` and `suggested_fix`. Only
PRIN-004..PRIN-007 are accepted; severity and `source_ref` must equal the
trusted rule catalog. Evidence is grounded only when `artifact` exists in the
materialized head and `location` is a resolvable JSON Pointer in that document.
Unknown/duplicate fields, unknown rules, mismatched trusted metadata, unsafe
paths and malformed status/verdict combinations make the response schema-
invalid. Forbidden credential, cookie, token, message or full-prompt fields
and common credential/private-key patterns reject the entire bundle before an
output can be written.

## Fixture metrics

These numbers validate the scorer and corpus plumbing only; they are not a
GigaAgent quality claim.

| metric | development (8) | holdout (8) | overall (16) |
|---|---:|---:|---:|
| expected / predicted findings | 4 / 4 | 4 / 4 | 8 / 8 |
| precision | 1.000 | 1.000 | 1.000 |
| recall | 1.000 | 1.000 | 1.000 |
| blocker recall | 1.000 (1/1) | 1.000 (1/1) | 1.000 (2/2) |
| outcome accuracy | 1.000 | 1.000 | 1.000 |
| exact case accuracy | 1.000 | 1.000 | 1.000 |
| schema-valid rate | 1.000 | 1.000 | 1.000 |
| invalid/hallucinated evidence rate | 0/4 = 0.000 | 0/4 = 0.000 | 0/8 = 0.000 |
| unsafe approve count | 0 | 0 | 0 |
| latency mean / p95 / max, ms | 10.625 / 15 / 15 | 10.688 / 17 / 17 | 10.656 / 17 / 17 |

The frozen numerical thresholds pass for the fixture in development, holdout
and overall scopes, but the release gate remains false because fixture mode is
never release-eligible.

## Frozen release gate

- blocker recall = 1.0;
- unsafe approve count = 0;
- schema-valid rate = 1.0;
- precision >= 0.80;
- recall >= 0.80;
- outcome accuracy >= 0.85.

Every threshold is evaluated separately for development, holdout and overall;
all three scopes must pass. A future real release result additionally requires
an authorised run through the organiser-defined capture contract and verified
adapter; an input bundle's `mode: real` label is explicitly insufficient.

## Reproduction

```bash
python3 evaluation/gigaagent/runner.py --verify-only
python3 evaluation/gigaagent/runner.py --materialize-check
pytest -q aga-skill/tests/test_gigaagent_evaluation.py
python3 evaluation/gigaagent/runner.py \
  --score-bundle evaluation/gigaagent/fixtures/sanitized-response-bundle.json \
  --mode fixture \
  --output evaluation/gigaagent/fixture-results.json
```

The negative tests prove that malformed schema, hallucinated evidence, unsafe
approve, sensitive raw fields, relabelled oracle fixtures, and fixture/real
mode mixing fail closed. They also prove that hostile global Git object-format,
hook, signing and filter configuration cannot affect synthetic materialisation.
An authorized real run is an external action and was intentionally not
performed.
