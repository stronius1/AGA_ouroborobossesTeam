# Ouroboros integration runbook and evidence boundary

**Status: real smoke and development evidence captured; frozen holdout has not
run.** `run-sanitized.json` records the canonical `ga-05-critical-eliminate`
smoke on orchestration prompt v1.0.5. `development-sanitized.json` records the
complete eight-case development selection on the same prompt and configuration.
Both were produced atomically by the trusted runner after locally validating
the full `aga_prepare_review → semantic review → aga_finalize_review` flow.

The development measurement captured at `2026-07-17T03:36:34Z` is 8/8 exact
PASS: precision, recall, blocker recall, outcome accuracy and schema-valid rate
are all `1.0`; unsafe approve count is `0`. Its authoritative model cost is
`0.231359 USD`. This remains non-release diagnostic evidence until the single
post-freeze 16-case development+holdout measurement succeeds.

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

### Verified local runtime path

On 2026-07-16 the downloaded `v6.64.1` DMG matched the pinned SHA-256 and passed
`hdiutil verify`, but macOS signature validation failed. The app bundle was not
installed and no signature bypass was used. The authorized fallback was built
from the exact upstream source commit above in an isolated environment. The
checkout remains clean and unmodified; all compatibility behavior lives in
project-owned launch-time code. Preflight verifies the source commit, installed
distribution version and live overlay attestation before a paid task can start.

## Active owner-controlled configuration

- the OpenRouter credential is persisted only in the dedicated owner-only
  Ouroboros settings file, as explicitly requested by the owner;
- the configured global hard cap is `50 USD`;
- every paid route is pinned to `deepseek/deepseek-v4-pro`, local routes and
  cross-model fallbacks are disabled;
- enforcement is Advisory and the extra host task-review lane is disabled;
- external skill `aga_review` version `1.0.0` is reviewed and enabled;
- AGA MCP is loopback-only at `127.0.0.1:8788`, without bearer auth, with
  exactly four discovered tools;
- only the locked `synthetic-public` corpus may be sent to OpenRouter.

The key must never be placed in CLI arguments, environment examples, Git, logs
or evidence. Preflight records only `credential_present: true`, validates the
positive cap, routes, review settings, skill state, isolated MCP configuration
and live runtime attestation, and never emits the credential value.

## Persistent isolated source profile

Project-owned runtime management uses a dedicated home outside Git. Its default
layout is:

```text
~/.local/share/aga-ouroboros-v6.64.1/
|-- source/                  # exact clean v6.64.1 source checkout
|-- venv/                    # isolated Python 3.12 environment
|-- home/                    # HOME visible to Ouroboros and its CLI
|   `-- Ouroboros/data/
|       |-- settings.json    # mode 0600; contains the credential
|       `-- skills/external/aga_review/
`-- tmp/
```

The profile directories are mode `0700`; the settings, PID and manager log
files are mode `0600`. The manager starts every child with `umask 077`. It does
not accept a key argument, does not copy provider credentials from its own
environment, and launches Ouroboros with a credential-free allowlisted
environment. `configure-key` reads from the controlling terminal with echo
disabled and writes the value atomically to `settings.json`; its JSON response
contains only `credential_present: true`. Ouroboros itself loads that supported
settings value into its internal server/worker environment, as implemented by
upstream v6.64.1; the project wrapper does not duplicate it in argv, shell
history, Make output or launch-time environment variables.

The normal lifecycle is:

```bash
make ouroboros-profile-init
make ouroboros-configure-key       # interactive, hidden input; normally once
make ouroboros-start
make ouroboros-status
make ouroboros-preflight           # ephemeral AGA MCP; no model task
make ouroboros-stop
```

`init` does not download or reinstall the runtime. `start` rejects any source
checkout other than commit `554b3eeeca345298d6dcc5711195ea9acec450bd`, a dirty
checkout, or an installed distribution other than `6.64.1`. The instruction
skill is copied into the isolated profile rather than symlinked. A changed
skill hash still requires the normal Ouroboros review and enable lifecycle
before preflight can pass.

The server process imports that verified source checkout explicitly. This is
required because the upstream v6.64.1 wheel omits repository review assets
(including `docs/CHECKLISTS.md`) that its skill-review code reads at runtime;
dependency installation remains disabled during server execution.

The project-owned v3 overlay applies three narrowly attested compatibility
policies without modifying the clean upstream checkout:

1. it replaces only the exact upstream post-task consolidation model constant
   with `deepseek/deepseek-v4-pro`;
2. it permits one physical retry only for the exact AGA `aga_finalize_review`
   call when MCP 1.28.1 surfaces the known post-success `ExceptionGroup`; the
   retry deep-copies identical arguments and any second public/model-initiated
   finalize is rejected;
3. for strictly identified managed `synthetic-public` AGA evaluation tasks it
   skips only paid post-task memory synthesis after the trusted result and cost
   checkpoint are complete. Ordinary/private tasks retain upstream behavior.

Spawn workers receive the guarded standard-library `sitecustomize` bootstrap
through a credential-free `PYTHONPATH`. The bootstrap installs deferred import
hooks and re-verifies the exact source before applying any policy. The owner-only
`0600` live attestation records `bootstrap_mode:
deferred_runtime_import_hooks`, `finalize_transport_retry:
exception_group_once` and `aga_post_task_policy:
skip_synthetic_public_memory_synthesis`. Preflight verifies these fields,
launcher/bootstrap hashes, source version/commit and live PID before emitting
`all_model_routes_pinned: true`.

One early development-only smoke, before the v3 route fix, invoked the upstream
Gemini post-task lane once and cost `0.061153 USD`. Only synthetic-public data
was involved; no holdout case, secret or real data was sent. The route was then
pinned fail-closed and all subsequent trusted evidence names only the selected
DeepSeek model.

For an intentionally different local location, set only non-secret path
overrides:

```text
AGA_OUROBOROS_PROFILE_HOME
AGA_OUROBOROS_VENV_DIR
AGA_OUROBOROS_SOURCE_DIR
AGA_OUROBOROS_BIN
AGA_OUROBOROS_PYTHON
```

The E2E and evaluation Make targets execute through the same profile manager,
so the CLI always resolves the matching profile port and settings without
putting the key in `.env` or the repository.

## Checkpoint workflow and current freeze candidate

Preflight and E2E are operator-controlled; ordinary offline CI must not invoke
them unconditionally:

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

The current canonical smoke (`ede1ec50`, captured at `2026-07-17T03:39:56Z`)
finished with the trusted PRIN-006 blocker, `request_changes_escalate`, HITL
required and no auto-merge. It cost `0.029781 USD`. The current development
selection uses these frozen-candidate values:

| Item | Value |
|---|---|
| Code-freeze commit | `873202fc9e726ebad8b031f0031b01f3b66b7fae` |
| Freeze timestamp (UTC) | `2026-07-17T03:45:05Z` |
| Prompt | `aga-skill/prompts/ouroboros-orchestration-v1.0.5.txt` |
| Prompt SHA-256 | `8366780b6d99a8eec94eebeaabcc00d7df6a80207a3883527eecfb9a1a5bdd16` |
| Secret-free config SHA-256 | `3267143de7e841c64b64f37195e671709e8437674e5d446394d09149bf542fc5` |
| Adapter SHA-256 | `43f5a9801bba3d021d6907c7c18478fe0faa260da9962a9a375bdd0fd6612219` |
| Corpus SHA-256 | `df2d16746342fe71dedadb04252bfdec9c670a2bed65fe001b784bba15bba951` |
| Ground truth SHA-256 | `80d465f0b01dff5acad92946b99d7009da987da7eeeb97df01f569415d33ad01` |

After the meaningful local code-freeze commit is recorded, the canonical
release measurement must run all 16 cases once in one trusted in-process
selection:

```bash
OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-all
```

Do not run `evaluate-ouroboros-holdout` separately: `evaluate-ouroboros-all`
already contains both frozen splits. The frozen holdout must not be used for
prompt tuning. A transport/provider failure does not authorize an unrecorded
repeat; owner direction is required before any retry.

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
