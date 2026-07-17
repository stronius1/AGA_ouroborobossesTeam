# Deterministic regression evidence snapshot v2

This directory freezes the hardened local synthetic run produced after the
evaluation-input and candidate-validation controls were completed. It is the
only retained deterministic snapshot; the superseded pre-hardening copy was
removed during repository cleanup.

The run evaluates 26 materialized cases. Baseline precision/recall/outcome
accuracy/exact-case accuracy/weighted cost are
`0.9524 / 1.0 / 0.9615 / 0.9615 / 2.0`; the isolated candidate reports
`1.0 / 1.0 / 1.0 / 1.0 / 0.0`. These are deterministic synthetic-regression
metrics, not official GigaAgent metrics.

Additional v2 integrity boundary:

- `aga.corpus-lock/v2` pins `golden/corpus.yaml`, every approved
  `golden/prs/**` byte and `fixtures/seaf.yaml`;
- baseline and candidate materialize the same private captured inputs;
- combined `fixtures_revision` is
  `46e0a8cd6accdd0b173f5711600c0f256f065f863ae7f077d3a6f53201d5f6d3`;
- base rules are captured once and revalidated before manifest creation;
- `scripts/apply_candidate.py` independently reproduces mutation, candidate,
  diff, metrics, gate, precedent, changelog and PR body, but cannot apply them;
- the recorded validation passed 19/19 checks with `sources_changed: false`
  and `apply_supported: false`.

`publisher-result.json` is a local dry-run record. No source rule was applied,
and no commit, branch, PR, merge, push or publication was performed.

Verify from the repository root:

```bash
cd docs/evidence/snapshots/deterministic-2026-07-15-v2
shasum -a 256 -c SHA256SUMS
```
