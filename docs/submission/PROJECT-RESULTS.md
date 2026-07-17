# AGA + SEAF Project Results

Evidence baseline: 2026-07-15; integration status updated 2026-07-17. Data is
synthetic and contains no production banking records or closed identifiers.

AGA turns a SEAF-native Architecture-as-Code change into an advisory,
evidence-backed governance review. SEAF.ArchTool is configured to render the
same manifest, but the pinned SEAF.ArchTool UI has not yet been executed locally;
AGA derives changed paths from immutable Git base/head revisions, maps SEAF
objects into `aga.canonical/v2`, performs deterministic guardrails, and exposes
prepare/lookup/diagram/finalize tools over MCP. Semantic PRIN-004..PRIN-007
tasks are reserved for the Ouroboros semantic stage. A missing or failed agent
stage is `incomplete`, never `approve`, at the AGA finalize boundary;
blocker/major always require HITL and merge is never automatic. The complete
live Ouroboros loop is now verified technically by a canonical blocker smoke
and a 16-case frozen run; that frozen run nevertheless failed its semantic
release gate and is not release evidence.

## 1. Отчёт о результатах фазы MVP — 20%

**Status: partial.** The local engineering scope contains:

- a project-owned synthetic SEAF manifest with components, integrations, ADRs,
  generated/custom diagram contexts and an ArchTool `ai-chat` scenario;
- a bounded import resolver and explicit SEAF → `aga.canonical/v2` mapping with
  file/JSON Pointer/hash provenance;
- a trusted Git snapshot layer designed around explicit base/head objects;
- a separate MCP transport and fail-closed prepare/finalize boundary;
- an opt-in Ouroboros `v6.64.1` materializer, read-only preflight, packaged-CLI
  backend and trusted one-case runner with offline contract tests;
- preserved 26-case deterministic regression evidence;
- a frozen independent 16-case semantic basket.

The original Project Proposal is absent, so promise-level traceability is
blocked rather than reconstructed. See
[`PROPOSAL-TRACEABILITY.md`](PROPOSAL-TRACEABILITY.md).

Architecture:

```text
SEAF.ArchTool + pinned seaf-core + synthetic architecture repo
                            |
           immutable base/head Git snapshot
                            v
 safe import closure -> aga.canonical/v2 -> deterministic findings
                            |
                   MCP prepare result
                            v
 Ouroboros v6.64.1: PRIN-004..007 + retrieval/tool orchestration
                            |
 strict MCP finalize -> verdict -> mandatory HITL / no auto-merge
```

## 2. Применение ГигаАгента в MVP — 10%

**Status: live integration works; frozen quality gate failed.** Ouroboros
`v6.64.1` was built from the exact verified upstream source commit in an
isolated owner-only profile after the downloaded macOS DMG failed signature
validation. Preflight attested the clean source, installed version, exact model
routes, reviewed skill and exactly four loopback AGA MCP tools. The OpenRouter
credential is persisted only in owner-only runtime settings outside Git, with
a `50 USD` hard cap.

The exact model route is `deepseek/deepseek-v4-pro`. The intended key scope is
semantic and impractical as simple field checks:
reuse-before-build (PRIN-004), one master (PRIN-005), prose-described critical
dependency (PRIN-006), and ADR necessity/quality (PRIN-007). Structured output
is allowlisted against prepared artifacts and trusted rule source references.
Raw prose cannot alter the verdict. The trusted runner captured prepare,
retrieval and finalize receipts, enforced exactly one public finalize result,
and accounted for model cost/tokens symmetrically. The canonical
`ga-05-critical-eliminate` smoke passed with a PRIN-006 blocker, mandatory HITL
and `auto_merge: false`.

Current frozen real-agent denominator: **16**. Ten cases passed exact scoring,
but holdout produced two unsafe approvals; therefore release status is
**FAIL**, not ready.

## 3. ДЕМО-видео — 30%

**Status: external action required.** No narrated public video or verified URL
exists. The recording plan in [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) is 2:50 and
shows the SEAF change, real Ouroboros run, MCP tools, deterministic and semantic
findings, final HITL verdict, and separate quality metrics. A recording may now
show the successful blocker smoke, but it must also state that the frozen
16-case release gate failed.

## 4. Документация и код — 10%

**Status: partial.** Root README, Make targets, version-pinned Python
requirements, npm lock usage, recursive submodule verification, CI definition,
Compose isolation and troubleshooting are prepared locally. The root repository
has no remote and no public URL; public availability and clean-clone CI
therefore remain external proof. GitHub Actions and Docker base images still
use mutable tags, and Python artifacts lack hashes, so byte-reproducible supply
chain evidence is not claimed.

The recorded pre-integration baseline is **381 pytest tests and 32 subtests
pass**; the independent unittest discovery reports **98 tests OK**. The
final post-integration verification on 2026-07-17 is **600 pytest tests and 32
subtests pass**, plus **99 unittest tests OK**, when loopback-dependent tests
run with the required local socket permission.

The two exact GitVerse revisions are recorded as pinned submodules and pass the
local gitlink/checkout integrity contract. Upstream Node/SEAF build and UI
validation are not yet claimed, and no recursive clean clone can be proven
until a permitted public remote exists. The local test branch now has an
immutable root history; no commit was pushed.

Expected local commands:

```bash
make bootstrap
make test
make test-seaf
make demo-offline
make project-results-check
```

`make demo-e2e` now invokes the opt-in trusted Ouroboros runner for
`ga-05-critical-eliminate`; it is not a fixture/sentinel. The authorized smoke
completed successfully and its sanitized evidence is retained. The canonical
`OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-all` command was then
executed exactly once after code freeze. It completed all tasks but exited with
`evaluation_gate_failed`; it must not be repeated for this frozen holdout.

## 5. Результаты на примерах — 20%

**Status: partial.** Denominators are kept separate.

Deterministic regression:

| Mode | Cases | Expected findings | Precision | Recall | Blocker recall | Outcome / exact accuracy | Weighted cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline 2.0.0 | 26 | 20 | 0.9524 | 1.0 | 1.0 | 0.9615 / 0.9615 | 2.0 |
| Isolated candidate | 26 | 20 | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | 0.0 |

All 26 per-case expected/predicted records, candidate rules and integrity
manifest are frozen in the
[`deterministic evidence snapshot`](../evidence/snapshots/deterministic-2026-07-15-v2/README.md).

GigaAgent basket:

| Split | Real cases | Exact pass | Precision | Recall | Blocker recall | Outcome | Schema valid | Unsafe approve | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Development | 8 | 6 | 0.75 | 0.75 | 1.0 | 0.875 | 1.0 | 0 | FAIL |
| Frozen holdout | 8 | 4 | 0.25 | 0.25 | 0.0 | 0.75 | 1.0 | 2 | FAIL |
| Overall | 16 | 10 | 0.50 | 0.50 | 0.50 | 0.8125 | 1.0 | 2 | FAIL |

The transport-free fixture scorer validates the basket/scoring machinery:
16/16 fixture cases pass, development and holdout precision/recall/blocker
recall/outcome/schema-valid are `1.0`, unsafe approve is `0`. This result has
`release_evidence: false` and is not a GigaAgent quality claim.

The basket covers positive/negative PRIN-004..007 cases, clean and blocker
outcomes, near-misses, prompt injection, missing context and multiple findings.
Human expected outputs and the release gate were locked before the real run.
The run used 85 accounted model calls and cost `0.409884 USD`. See
[`../evidence/evaluation/RESULTS.md`](../evidence/evaluation/RESULTS.md) and the
explicitly non-release
[`frozen failure record`](../evidence/ouroboros/frozen-run-failure-sanitized.json).

## 6. Качество материалов — 10%

**Status: partial.** Current materials follow one narrative: problem → SEAF
source → role of the agent → AGA safety boundary → E2E → measured results →
limitations → next actions. C6 is consistently named «Качество материалов».
Presentation source and regenerated 8-page PDF use one compact visual system
and report the failed real gate rather than a zero denominator. A final
independent editorial review and video link are still required.

## Limitations and owner actions

The local MVP is not Project Results complete. Remaining owner-controlled and
external actions are:

1. the original Project Proposal;
2. verify ArchTool build/UI and SEAF validators, then prove a recursive clean
   clone after a permitted public remote exists;
3. redesign the generic semantic strategy without tuning on the revealed
   holdout, then freeze a new untouched holdout before any future paid release
   cycle;
4. a public repository and unauthenticated clean-clone proof;
5. a narrated video strictly shorter than 180 seconds and a verified public URL;
6. verified immutable GitHub Action SHAs, Docker image/OS-package digests and
   Python artifact hashes, followed by a clean-clone CI run;
7. final submission and any external communication.
