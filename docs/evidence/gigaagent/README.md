# Official GigaAgent evidence boundary

**Status: not run.** The project-owned Ouroboros materializer, preflight,
backend and trusted runner are implemented and covered by offline contract
tests, but no real Ouroboros task or model request has completed in this
workspace. Consequently:

- the canonical `docs/evidence/ouroboros/run-sanitized.json` is intentionally
  absent, and this directory never receives a duplicate trace;
- the real denominator in `evaluation/gigaagent/results.json` is `0`;
- fixture/local adapter output is not copied into this directory;
- `make demo-e2e` invokes the opt-in one-case trusted runner rather than a
  fixture/sentinel; with the current missing runtime configuration it fails
  closed as `not_configured` and creates no evidence.

The real-agent denominator therefore remains `0`. Fixture scoring and offline
adapter tests do not change it. Relabelling fixture output or supplying
plausible runtime/model names is not official provenance and cannot produce
release evidence.

After an authorised real run through the validated capture contract, the
canonical Ouroboros trace may be added only if it
contains the date, official runtime/model/version, prompt/config hashes,
actual base/head commits, invoked AGA tools, normalized findings, available
latency/token usage, final status/verdict, and a redaction note. Credentials,
cookies, bearer values, full closed prompts and non-synthetic data are
forbidden.
