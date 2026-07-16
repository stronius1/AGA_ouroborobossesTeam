# AGA + SEAF Project Results

Evidence baseline: 2026-07-15; integration status updated 2026-07-16. Data is
synthetic and contains no production banking records or closed identifiers.

AGA turns a SEAF-native Architecture-as-Code change into an advisory,
evidence-backed governance review. SEAF.ArchTool is configured to render the
same manifest, but the pinned UI/runtime has not yet been executed locally;
AGA derives changed paths from immutable Git base/head revisions, maps SEAF
objects into `aga.canonical/v2`, performs deterministic guardrails, and exposes
prepare/lookup/diagram/finalize tools over MCP. Semantic PRIN-004..PRIN-007
tasks are reserved for the Ouroboros semantic stage. A missing or failed agent
stage is `incomplete`, never `approve`, at the AGA finalize boundary;
blocker/major always require HITL and merge is never automatic. Enforcement by
the complete live loop remains unverified until a real sanitized Ouroboros
capture exists.

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

**Status: external runtime action required.** The pinned packaged-CLI adapter,
preflight and capture contract are implemented, but they do not prove a live
Ouroboros run. No real task, model request or sanitized trace has completed.
The OpenRouter key has not been persisted in project files or passed by the
runner, and no hard budget cap has yet been supplied for a paid call.
The downloaded macOS `v6.64.1` DMG matched the guide SHA-256 and passed
`hdiutil verify`, but `codesign --verify` reported an invalid signature and
`spctl` returned an internal error. It was therefore not installed or launched.

The exact model route is `deepseek/deepseek-v4-pro`. The intended key scope is
semantic and impractical as simple field checks:
reuse-before-build (PRIN-004), one master (PRIN-005), prose-described critical
dependency (PRIN-006), and ADR necessity/quality (PRIN-007). Structured output
is allowlisted against prepared artifacts and trusted rule source references.
Raw prose cannot alter the verdict. The real run must produce sanitized
prepare, retrieval and finalize traces; their absence leaves the result
`incomplete`.

Current real-agent denominator: **0**. Fixture/local adapters remain
development evidence only.

## 3. ДЕМО-видео — 30%

**Status: external action required.** No narrated public video or verified URL
exists. The recording plan in [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) is 2:50 and
shows the SEAF change, real Ouroboros run, MCP tools, deterministic and semantic
findings, final HITL verdict, and separate quality metrics. It must not be
recorded as final until a permitted Ouroboros E2E succeeds.

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
post-integration offline verification on 2026-07-16 is **489 pytest tests and
32 subtests pass**, with the same **98 unittest tests OK**. This does not alter
the real-agent denominator.

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
`ga-05-critical-eliminate`; it is not a fixture/sentinel. Without the pinned
runtime and complete owner configuration it fails closed as `not_configured`
and creates no evidence. It is not run in public CI. A successful first smoke
must stop at that one case; the full 16-case development/holdout evaluation
requires a separate explicit confirmation. The canonical release command is
`OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-all`; individual
split commands produce non-release diagnostic evidence only.

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

| Split | Materialized cases | Real cases evaluated | Metrics status |
|---|---:|---:|---|
| Development | 8 | 0 | not run |
| Frozen holdout | 8 | 0 | not run |

The transport-free fixture scorer validates the basket/scoring machinery:
16/16 fixture cases pass, development and holdout precision/recall/blocker
recall/outcome/schema-valid are `1.0`, unsafe approve is `0`. This result has
`release_evidence: false` and is not a GigaAgent quality claim.

The basket covers positive/negative PRIN-004..007 cases, clean and blocker
outcomes, near-misses, prompt injection, missing context and multiple findings.
Human expected outputs and the release gate were locked before a real run.
See [`../evidence/evaluation/RESULTS.md`](../evidence/evaluation/RESULTS.md).

## 6. Качество материалов — 10%

**Status: partial.** Current materials follow one narrative: problem → SEAF
source → role of the agent → AGA safety boundary → E2E → measured results →
limitations → next actions. C6 is consistently named «Качество материалов».
Presentation source and generated PDF use one compact visual system. A final
independent editorial review is still required after real metrics and video
links exist.

## Limitations and owner actions

The local MVP is not Project Results complete. Remaining owner-controlled and
external actions are:

1. the original Project Proposal;
2. verify ArchTool build/UI and SEAF validators, then prove a recursive clean
   clone after a permitted public remote exists;
3. register only the full immutable synthetic base/head SHAs produced by the
   trusted materializer for the local E2E;
4. resolve the blocked Ouroboros runtime installation, configure the exact
   model routes, reviewed/enabled `aga_review` skill, isolated AGA MCP,
   Advisory enforcement, `OUROBOROS_TASK_REVIEW_MODE=off`, credential and an
   explicit positive hard budget cap;
5. run only the permitted `ga-05-critical-eliminate` smoke and retain sanitized
   evidence only after all capture checks pass;
6. separately confirm spend before the full 16-case development/holdout run;
7. a public repository and unauthenticated clean-clone proof;
8. a narrated video strictly shorter than 180 seconds and a verified public URL;
9. verified immutable GitHub Action SHAs, Docker image/OS-package digests and
   Python artifact hashes, followed by a clean-clone CI run;
10. final submission and any external communication.
