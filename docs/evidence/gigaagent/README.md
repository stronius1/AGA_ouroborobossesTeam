# Official GigaAgent evidence boundary

**Status: the frozen real run completed all 16 cases and FAILED the release
gate.** The project-owned Ouroboros materializer, preflight, backend and trusted
runner executed through Ouroboros `v6.64.1`, OpenRouter and exact model
`deepseek/deepseek-v4-pro`. Technical task, receipt, schema and accounting
checks completed; semantic scoring passed 6/8 development and 4/8 holdout cases
and produced two unsafe approvals.

The measurement denominator is therefore `16`, but there is no passing release
denominator. `evaluation/gigaagent/results.json` intentionally remains its
checked-in zero-denominator PASS-only sentinel: the trusted writer overwrites
that canonical file only after all development, holdout and overall thresholds
pass. It must not be edited or relabelled to disguise a failed gate.

Evidence boundaries:

- canonical blocker smoke:
  [`../ouroboros/run-sanitized.json`](../ouroboros/run-sanitized.json);
- final pre-freeze development diagnostic:
  [`../ouroboros/development-sanitized.json`](../ouroboros/development-sanitized.json);
- post-failure, explicitly non-release sanitized diagnostic:
  [`../ouroboros/frozen-run-failure-sanitized.json`](../ouroboros/frozen-run-failure-sanitized.json);
- fixture/local adapter output is not copied into this directory and never
  becomes real evidence by relabelling.

No retry was performed. The frozen holdout must not be used for tuning or run
again. A future release attempt requires a revised generic strategy, a new
untouched holdout and a separately authorized paid cycle.

Credentials, cookies, bearer values, full closed prompts, raw provider payloads,
absolute local paths and non-synthetic data remain forbidden in evidence. Only
`synthetic-public` data was sent during the completed run.
