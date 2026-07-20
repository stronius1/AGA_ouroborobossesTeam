# AGA + Ouroboros

Self-evolving Architecture Governance Agent для review Architecture-as-Code.

## За 30 секунд

Архитекторы вручную сверяют каждый PR с SEAF, ADR, диаграммами и принципами;
это создаёт очередь и неодинаковое качество review. AGA строит trusted snapshot
immutable `base/head`, находит нарушения с точным evidence и возвращает
advisory verdict. Ouroboros выполняет semantic review, remediation и re-review
через ограниченный AGA MCP boundary. Параллельно candidate правила проверяется
на 26 materialized golden cases. Обе ветки должны пройти единый пятичековый
safety gate; человек остаётся обязательным, auto-merge отсутствует.

```text
Architecture PR ──> review ──> remediation ──> re-review ──┐
                                                          ├─> 5-check gate ─> HITL
Human precedent ──> rule candidate ──> 26× baseline/candidate ┘               merge=false
```

Текущий статус честно ограничен: бесплатный локальный E2E воспроизводим,
controlled synthetic-public Ouroboros flow с тремя реальными задачами прошёл,
но нового broad semantic release PASS нет. Исторический frozen 16-case run
получил `FAIL` и два unsafe approve; старый holdout повторно не используется.
Новый `development-v2` уже содержит 48 locked synthetic-public кейсов, но его
independent human review и пять платных повторов ещё не выполнены, поэтому
корпус не выдаётся за quality evidence.
Public repository, video и Project Results PDF URL пока не опубликованы.

Быстрые ссылки:

- [Project Results](docs/AGA-Ouroboros-Project-Results.pdf)
  ([канонический Markdown](docs/PROJECT-RESULTS.md))
- [Proposal → MVP traceability](docs/PROPOSAL-TRACEABILITY.md)
- [Бизнес-эффект и sensitivity](docs/BUSINESS-EFFECT.md)
- [Презентация Project Results](docs/AGA-Ouroboros-Project-Results.pptx)
  ([редактируемый Markdown](docs/PRESENTATION.md))
- [Self-evolution runbook](docs/SELF-EVOLUTION-RUNBOOK.md)
- [Development-v2: 48 кейсов и measurement gate](evaluation/development-v2/README.md)
- [Канонические submission-факты](docs/SUBMISSION-FACTS.json)

## Local quick start

Нужны Python 3.10+, Git и version-pinned packages. Для полного ArchTool
bootstrap дополнительно нужны Node 20 и npm 8.1+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r aga-skill/requirements-dev.txt

make demo-verify
make self-evolution-ui
```

Откройте `http://127.0.0.1:8090`, оставьте режим «Бесплатный локальный E2E» и
нажмите «Проверить весь E2E · $0». UI слушает loopback и не требует network,
credentials или model calls.

`make demo-verify` предварительно удаляет только cache-файлы, материализует
детерминированный candidate, запускает UI/scenario/E2E contracts, фактический
local review → remediation → re-review, 26 baseline/candidate cases, unified
gate, locked development-v2 contracts, pins/secrets/evidence и submission
consistency. Paid Live preflight и calls в этот target не входят.

## Что произойдёт в Demo

Full preset генерирует новый `synthetic-public` граф из 11 узлов и 9 потоков.
Один поток намеренно направлен в `demo.legacy_scoring` со статусом `eliminate`.

1. Детерминированный architecture review подтверждает `SEAF-004`.
2. Remediation использует только явный `replaced_by: demo.scoring_v2` и меняет
   одну строку `to`.
3. Re-review подтверждает закрытие finding и отсутствие новых нарушений.
4. Rule evolution исправляет false finding только в `pr-15`.
5. Четыре baseline и четыре candidate workers обрабатывают все 26 golden
   cases; `pr-16` остаётся negative control.
6. Safety gate проверяет workspace, закрытие `SEAF-004`, все candidate tests,
   отсутствие rule regression и строгое улучшение.

Ожидаемый результат:

- baseline: 25/26; candidate: 26/26;
- изменившийся behavior: только `pr-15`; `pr-16` остаётся защищённым;
- architecture finding: 1 → 0;
- gate: пять из пяти checks passed;
- `human_review_required=true`, `auto_merge=false`, external side effects=false;
- локальные JSON/diff/manifest artifacts имеют SHA-256.

## Архитектура и trust boundary

```text
SEAF.ArchTool runtime                    architecture/ synthetic SEAF workspace
  pin 83c82ab...                           seaf-core pin 60ce3358...
             \                              /
              trusted Git base/head snapshot
                         |
         deterministic SEAF / ADR / diagram guardrails
                         |
                  AGA MCP prepare
                         |
          Ouroboros semantic PRIN-004..007
                         |
                  AGA MCP finalize
                         |
              advisory verdict + evidence
                         |
          candidate-only remediation / re-review
                         |
                       HITL
```

Модель не получает произвольный filesystem path, credentials или право
изменять repository. Trusted host разрешает только зарегистрированные
revisions/cases, валидирует schema/evidence и применяет аттестованный patch
только в отдельном локальном candidate worktree.

## Роль Ouroboros и Live prerequisites

Ouroboros `v6.64.1` нужен для semantic review и для трёх задач controlled
self-evolution: review-before, remediation и review-after. Канонический
retained run через OpenRouter и `deepseek/deepseek-v4-pro` завершился локальным
candidate с gate PASS и известной суммарной стоимостью `0.113183 USD`; это не
broad semantic release.

Активный development-контракт использует versioned skill/prompt `v1.1.0` с
изолированными rule results, predicate coverage и fail-closed unresolved
references. Historical `v1.0.0`/prompt `v1.0.5` не перезаписаны: именно их
hashes остаются provenance старого frozen evidence.

Live режим опционален и платный. До любого вызова нужны:

- чистый pinned source/runtime `v6.64.1` и attested overlay;
- owner-configured OpenRouter key только во внешнем owner-only profile;
- positive hard cap и достаточный remaining budget;
- exact allowlisted model route;
- reviewed/enabled `aga_review` skill;
- loopback AGA MCP gateway с 6 tools и worker envelopes review=4,
  remediation=2;
- явное подтверждение paid run в UI/CLI.

```bash
make ouroboros-profile-init
make ouroboros-profile-sync
make ouroboros-configure-key
make ouroboros-start
make ouroboros-preflight   # read-only, no model call

# paid synthetic-public smoke только с отдельного разрешения владельца
make demo-e2e
```

Точные prerequisites, budget/error codes и recovery:
[`docs/SELF-EVOLUTION-RUNBOOK.md`](docs/SELF-EVOLUTION-RUNBOOK.md).

## Метрики: пять разных границ

| Measurement | Результат | Разрешённый вывод |
|---|---|---|
| 26-case deterministic fitness | 25/26 → 26/26; precision 0.9524 → 1.0; recall/blocker recall 1.0 | Candidate rule улучшил один golden case без регрессии |
| Controlled live self-evolution | 3 real tasks; gate PASS; `0.113183 USD` | Ouroboros/MCP review → remediation → re-review работает E2E |
| Development-v2 corpus | 48 locked cases; human review `pending`; series `pre_measurement` | Инженерное покрытие PRIN-004..007 готово к независимой проверке; model quality ещё не измерено |
| 16-case fixture | 16/16; `release_evidence=false` | Scorer/corpus/gate plumbing работает |
| Historical frozen real semantic run | 10/16; precision/recall/blocker recall 0.50; outcome 0.8125; unsafe approve 2; gate FAIL | Старый freeze не release-ready |

`evaluation/gigaagent/results.json` остаётся PASS-only sentinel со статусом
`not_run` и denominator 0: текущего trusted all-case PASS нет. Исторический
FAIL сохранён отдельно и не переписан optimistic результатом. Подробности:
[evaluation results](docs/evidence/evaluation/RESULTS.md).

Для `development-v2` есть бесплатный offline series verifier. Он заново
скорит ровно пять distinct HMAC-attested captures с frozen
model/prompt/config/selection identity и внешним ключом серии, считает worst-case thresholds,
approve/non-approve flapping, p95, tokens и cost caps. Значения latency/cost
задаёт команда — defaults намеренно отсутствуют:

```bash
make verify-development-v2-series \
  DEVELOPMENT_V2_SERIES_INPUTS="repeat-1.json repeat-2.json repeat-3.json repeat-4.json repeat-5.json" \
  DEVELOPMENT_V2_ATTESTATION_KEY_FILE=<external-key-file> \
  DEVELOPMENT_V2_MAX_P95_MS=<team-p95-budget-ms> \
  DEVELOPMENT_V2_MAX_COST_USD=<team-cost-cap-usd>
```

Команда анализирует уже сохранённые captures и не выполняет model calls.

## Safety и HITL

- `blocker`/`major` всегда требуют человека; clean result — только advisory
  `approve`.
- Missing context, schema/import/tool errors и invalid evidence завершаются
  fail-closed `incomplete`/`error`.
- Semantic findings проходят strict schema, rule/source allowlist и проверку
  location по переданному snapshot.
- Во внешнюю модель разрешены только `synthetic-public` inputs; raw prompts,
  provider payloads, secrets и absolute paths не входят в evidence.
- Remediation MVP ограничен `SEAF-004` и никогда не угадывает successor.
- Candidate rules/architecture не применяются к main автоматически; push,
  approve, merge и auto-merge отсутствуют.

## Evidence и воспроизводимость

| Evidence | Что содержит |
|---|---|
| [Deterministic snapshot](docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md) | 26-case baseline/candidate metrics, diff, manifest и SHA256SUMS |
| [Controlled self-evolution](docs/evidence/ouroboros-self-evolution-v1.json) | Три task IDs, receipts, model/cost, patch и HITL gate |
| [Accepted semantic smoke](docs/evidence/ouroboros/run-sanitized.json) | Реальный blocker smoke, strict sanitized capture |
| [Historical frozen FAIL](docs/evidence/ouroboros/frozen-run-failure-sanitized.json) | 16-case real metrics, cost и unsafe approvals |
| [Development-v2](evaluation/development-v2/README.md) | 48 новых development cases, strict scorer и hashes; human review pending |
| [Semantic report](docs/evidence/evaluation/RESULTS.md) | Fixture/real boundaries, thresholds и reproduction |
| [Submission facts](docs/SUBMISSION-FACTS.json) | Единый machine-readable источник цифр и public URL |

Проверки:

```bash
make project-results-check
make submission-consistency-check
make check-secrets
```

GitHub Actions закреплены полными commit SHA, базовый Docker image — manifest
digest, Python wheels в CI/container — SHA-256, а apt использует датированный
Debian snapshot. Это закрывает известные content-addressing warnings; scope
остаётся ограничен Git/image/wheel pins, version manifests, npm lock integrity
и retained evidence, а не побитовой воспроизводимостью любой host-системы.

## Repository map

- [`architecture/`](architecture/) — synthetic SEAF-native objects и project
  extension.
- [`aga-skill/`](aga-skill/) — review engine, rules, evolver, MCP adapters и
  tests.
- [`scripts/`](scripts/) — trusted runners, profile/preflight, demo и hygiene.
- [`self-evolution-ui/`](self-evolution-ui/) — loopback Control Room.
- [`evaluation/gigaagent/`](evaluation/gigaagent/) — 16-case semantic corpus,
  scorer и gates.
- [`evaluation/development-v2/`](evaluation/development-v2/) — 48-case
  development-only corpus, Git materializer, strict scorer и paid guard.
- [`docs/`](docs/) — contracts, runbooks, submission materials и evidence.
- `seaf-archtool-core/` — pinned GitVerse submodule
  `83c82ab1673f1245b499c26b82d507fa602a11d6`.
- `architecture/vendor/seaf-core/` — pinned GitVerse submodule
  `60ce335832d2734814c020306a85d1e8b12cf67b`.

## Команды

| Команда | Назначение |
|---|---|
| `make demo-verify` | Единый бесплатный local submission/demo gate |
| `make self-evolution-ui` | Запустить loopback UI |
| `make test` | Полный Python regression/contract suite |
| `make test-seaf` | Pins, SEAF adapter, ArchTool tests/build |
| `make demo-offline` | Изолированный deterministic review без model calls |
| `make ouroboros-preflight` | Read-only Live readiness; без model call |
| `make demo-e2e` | Один opt-in paid semantic blocker smoke |
| `make architecture-self-evolution` | Controlled live review/remediation/re-review, candidate-only |
| `make loop-a-local-candidate` | Rule evolution и локальный candidate, без remote |
| `make self-evolution` | Оба candidate-only контура; требует готового Live profile |
| `make project-results-check` | Pins, secrets, links, evidence и hygiene |
| `make submission-consistency-check` | Сверить docs/facts с evidence и business formulas |
| `make clean-caches` | Удалить только cache-файлы, сохранив evidence/build artifacts |
| `make semantic-stability-report STABILITY_INPUTS="..." STABILITY_MAX_P95_MS="..." STABILITY_MAX_COST_USD="..."` | Offline aggregator для прежнего gigaagent result schema; все inputs/budgets обязательны |
| `make verify-development-v2` | Offline validation, lock/scorer/contracts и Git materialization без model calls |
| `make evaluate-ouroboros-development-v2 DEVELOPMENT_V2_PAID_APPROVED=yes DEVELOPMENT_V2_REPEAT_ORDINAL=1 DEVELOPMENT_V2_CAPTURE_ID=<unique-id> DEVELOPMENT_V2_ATTESTATION_KEY_FILE=<external-key-file>` | Один из пяти full paid repeats; дополнительно требует accepted human review и frozen identity |
| `make verify-development-v2-series DEVELOPMENT_V2_SERIES_INPUTS="..." DEVELOPMENT_V2_ATTESTATION_KEY_FILE=<external-key-file> DEVELOPMENT_V2_MAX_P95_MS="..." DEVELOPMENT_V2_MAX_COST_USD="..."` | Authenticate и re-score пяти distinct captures, worst-case/flapping/latency/tokens/cost; budgets обязательны |

Full 16-case semantic evaluation намеренно защищён отдельным
`OUROBOROS_FULL_RUN_APPROVED=yes`. Для раскрытого freeze нельзя повторять
holdout/all-run; следующий release требует нового holdout.

## Troubleshooting

- `dependency_not_initialized`: `git submodule update --init --recursive`,
  затем `make verify-pins`.
- `candidate rules directory not found`: `cd aga-skill && python3
  scripts/run_evolution.py --demo`; `make demo-verify` делает это автоматически.
- `not_configured` в Live: проверьте profile, exact model route, hard cap,
  reviewed skill и MCP envelopes по runbook.
- UI не открывается: убедитесь, что `127.0.0.1:8090` свободен; изменять bind на
  внешний интерфейс для demo не нужно.
- `project-results-check` нашёл caches: выполните `make clean-caches`, затем
  повторите проверку; checker не удаляет hygiene defects сам.
- ArchTool build требует Node 20/npm 8.1+ и инициализированные submodules.

## Known limitations и материалы подачи

- Public repository URL, demo video URL и Project Results PDF URL пока
  отсутствуют; public clean clone не проверен.
- Новый trusted broad semantic release PASS отсутствует.
- Development-v2 human review, series freeze и пять стабильных повторов не
  выполнены; paid target до этого fail-closed.
- Поддерживается одна bounded architecture remediation `SEAF-004`.
- Business-effect `5.35 ч/нед`, `≈4.1 млн ₽`, `≈15×` — scenario hypothesis с
  явными допущениями, не production ROI.
- Известные CI/container supply-chain inputs content-addressed; полная Docker
  build-rehearsal на этой машине не выполнена, потому что daemon недоступен.

Материалы:

- [Project Results report](docs/PROJECT-RESULTS.md)
- [Presentation outline](docs/PRESENTATION-OUTLINE.md)
- [Demo video script](docs/DEMO-VIDEO-SCRIPT.md)
- [Final submission checklist](docs/SUBMISSION-CHECKLIST.md)
- [Project Proposal PDF](Project_Proposal_AGA_SberAIHack.pdf)
