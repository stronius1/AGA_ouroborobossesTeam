# Ouroboros integration runbook and evidence boundary

**Status: real run not captured.** This directory documents the trusted run
boundary. `run-sanitized.json` must remain absent until the real runner has
completed and locally validated a full
`aga_prepare_review → semantic review → aga_finalize_review` flow.

The project-owned materializer, read-only preflight, packaged-CLI backend and
trusted smoke/evaluation runners are implemented and exercised by offline
contract tests. That implementation evidence is not a real-agent result: no
Ouroboros task or OpenRouter request has been made, the real-agent denominator
is still `0`, and no key has been persisted by the project.

## Pinned runtime

The only accepted runtime for this evidence version is the official
[Ouroboros `v6.64.1` release](https://github.com/razzant/ouroboros/releases/tag/v6.64.1).

| Item | Pinned value |
|---|---|
| Source commit | `554b3eeeca345298d6dcc5711195ea9acec450bd` |
| macOS DMG SHA-256 | `783c043920c57f0b373de6d3d35eb8bf5de87b019ee0f4fb2619e8e7cbaf5e18` |
| Linux TAR.GZ SHA-256 | `514425bace50b5bffb52e1f4c1ec1f2d095a5ceb6a431e86259010a87ddc363c` |
| Windows ZIP SHA-256 | `c2d3bc4b560355b9a2e389e33bab58aa4c79ae3973199f9e53cb32fac9bc7897` |
| Provider | `openrouter` |
| Main/semantic model | `deepseek/deepseek-v4-pro` |
| Initial review mode | `advisory` |

### Local macOS verification checkpoint

On 2026-07-16 the downloaded `v6.64.1` DMG matched the pinned SHA-256 above and
passed `hdiutil verify`. Both the mounted app verification and the DMG
`codesign --verify` check nevertheless failed with `invalid signature (code or
signature have been modified)`, while `spctl` returned an internal error. The
app was therefore not copied, installed or launched. This hash match is not
being presented as a valid platform signature, and no bypass is authorised by
this runbook.

Source-level inspection, when needed, must use the exact tag and commit above;
project integration must not modify Ouroboros sources. A trusted runtime path
must be resolved before preflight can become ready or any model call can occur.

## Owner-controlled preconditions

Before any model call, the owner must:

1. install and start a trusted packaged Ouroboros `v6.64.1` runtime; the locally
   checked macOS asset is currently blocked by the signature failure above;
2. enter the OpenRouter credential manually in **Ouroboros Settings → Secrets**;
3. route `OUROBOROS_MODEL` exactly to the model above. Heavy, Light, Vision and
   Consciousness must be empty or the same exact model; Deep Self Review,
   Websearch, Scope Review, every Review Model and every Scope Review Model must
   be the same exact model. All local-model routes must be disabled and
   `OUROBOROS_MODEL_FALLBACKS` must be empty;
4. provide and configure an explicit positive hard budget cap in USD. No cap
   has been supplied yet, so a paid call remains blocked;
5. keep review enforcement in Advisory mode and set
   `OUROBOROS_TASK_REVIEW_MODE=off` so the host does not add a second paid
   review outside AGA;
6. install `ouroboros-skill/aga-review` as external skill `aga_review` version
   `1.0.0`, run Ouroboros's standard skill review, and have the owner explicitly
   enable the reviewed, non-stale instruction skill with no permissions;
7. register only the loopback AGA MCP endpoint
   `http://127.0.0.1:8788/mcp`, without bearer auth, and discover exactly the
   four AGA tools;
8. confirm that every file sent externally belongs to the locked
   `synthetic-public` corpus.

The key and hard-cap value are operator inputs. The key must never be placed in
CLI arguments, environment examples, Git, logs, evidence or chat output.
Preflight checks masked credential presence, the positive hard cap, every model
route listed above, review settings, skill review/enable state, isolated MCP
configuration and exactly four AGA tools. It is read-only, does not start a
task, and does not read the credential or cap value into evidence.

## Checkpoint workflow

The first command is offline-only. Preflight and E2E are operator-controlled;
ordinary offline CI must not invoke them unconditionally:

```bash
make ouroboros-materialize
make ouroboros-preflight
make demo-e2e
```

The project-local materialization is an offline preview only. The real runner
revalidates and rematerializes the case under the neutral
`/private/tmp/aga-synthetic-public/ouroboros-cases` root so an Ouroboros
`active_workspace` field cannot disclose a user-specific absolute path to the
provider.

The first smoke case is `ga-05-critical-eliminate`. It must finish with a
trusted blocker, `request_changes_escalate`, HITL required and no auto-merge.
If the runtime, model, budget, MCP registry or credential is absent, the runner
must fail non-zero with typed `not_configured` and must not create evidence.

Stop after that one smoke. Run the two eight-case baskets only after a new,
explicit owner confirmation of the spend and budget cap:

```bash
OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-development
OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-holdout
```

The environment gate is an accidental-run safeguard, not owner consent. The
frozen holdout must not be used for prompt tuning. A transport/provider failure
does not authorize an unrecorded repeat.

## Sanitized capture contract

Only the trusted runner may atomically create `run-sanitized.json`, and only
after schema, receipt correlation and case acceptance pass. A valid capture may
contain:

- runtime version, provider and exact model ID;
- prompt/config/corpus hashes;
- synthetic case ID plus full base/head commit IDs;
- task IDs, bounded latency and sanitized token/cost totals;
- ordered AGA tool names and receipt/output hashes;
- normalized findings and the AGA finalize verdict;
- HITL and no-auto-merge flags;
- a redaction statement.

It must not contain credentials, auth headers, absolute local paths, raw
prompts, provider request/response payloads, cookies or non-synthetic data.
`python3 scripts/check_secrets.py` must pass before the capture is retained.
Manually assembled or relabelled fixture JSON is not real evidence.

No command in this runbook authorizes push, merge, PR publication, remote
comments, public deployment or auto-evolution.
