# Deterministic regression evidence snapshot

This directory freezes the 15 July 2026 local, synthetic deterministic run that
is summarized in `aga-skill/docs/RESULTS-EXAMPLES.md`. The machine-readable
metrics contain all 26 `per_pr` records, expected/predicted findings and verdict
comparison. They are deliberately separate from the zero-denominator real
GigaAgent result and from the non-release GigaAgent fixture score.

Contents:

- `metrics-baseline.json`: rules v2.0.0, 26 evaluated cases;
- `metrics-candidate.json`: isolated v2.1.0 candidate, 26 evaluated cases;
- `candidate-manifest.json`, `candidate-rules/`, `rules.diff`,
  `evolution-pr.md`, precedent and changelog entry: the isolated candidate and
  its human-review handoff;
- `publisher-result.json`: evidence that no publication was performed;
- `SHA256SUMS`: integrity manifest for every copied payload.

The candidate passed its local deterministic gate but was not applied, merged,
committed or published. The top-level project currently has no authorized
commit, so this directory is a prepared project-owned evidence snapshot rather
than a claim of public or clean-clone availability.

Verify from the repository root:

```bash
cd docs/evidence/snapshots/deterministic-2026-07-15
shasum -a 256 -c SHA256SUMS
```
