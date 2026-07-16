# AGA Skill — Architecture Governance Agent MVP

AGA проверяет Architecture-as-Code изменения: получает фактический base/head
diff из Git, безопасно материализует import/context closure SEAF/DocHub,
преобразует объекты в `aga.canonical/v2`, исполняет guardrails и создаёт
candidate изменения правил по подтверждённым прецедентам. Blocker/major всегда
уходят человеку; auto-merge отсутствует.

Текущий доказанный scope — offline deterministic MVP, trusted Git snapshot,
SEAF-native adapter и локальные transport/contract tests. Реальные ГигаАгент,
Ouroboros A2A и draft-PR connector не подключены; они перечислены как внешние
действия, а не как готовый функционал.

Актуальный командный handoff со статусом, ограничениями и приоритетным планом:
[`docs/CURRENT-STATE-AND-ROADMAP.md`](docs/CURRENT-STATE-AND-ROADMAP.md).

## Команды установки и запуска

Нужен Python 3.10+; команды выполняются из каталога `aga-skill/`.

```bash
python3 -m venv .venv                         # 1
source .venv/bin/activate                     # 2 (Windows: .venv\Scripts\activate)
python3 -m pip install -r requirements-dev.txt # 3, exact pinned versions
make test                                     # 4, полный offline suite
make demo                                     # 5, blocker review → evolution → artifacts
```

Версии зависимостей закреплены. Установка в пустой venv в текущей
среде не проверена: внешняя сеть запрещена, а полного локального wheel
cache нет. Команды `make test` и `make demo` подтверждены в уже
подготовленном локальном окружении.

`make demo` принимает только ожидаемый exit `1` blocker-review, затем запускает
эволюцию, печатает baseline/candidate metrics и проверяет артефакты. Любой иной
неожиданный exit останавливает demo.

Exit-коды `scripts/run_review.py`:

- `0` — `approve` или `approve_with_warnings`;
- `1` — штатная HITL-эскалация blocker/major;
- `2` — malformed/unsafe input, incomplete mandatory LLM или adapter/log error.

Примеры:

```bash
python3 scripts/run_review.py --pr golden/prs/pr-12       # SEAF-004, exit 1
python3 scripts/run_review.py --pr golden/prs/pr-01       # clean, exit 0
python3 scripts/run_review.py --pr golden/prs/pr-01 --mode llm
# Без explicit adapter: incomplete, exit 2 (fail closed).
python3 scripts/run_review.py --pr golden/prs/pr-01 --mode llm \
  --llm-fixture /path/to/synthetic-findings.json --format json --no-log
# Fixture ответ помечен synthetic_fixture_non_release и не является
# release-доказательством качества агента.
python3 scripts/run_seaf_review.py --case demo-critical-dependency --mode offline
# Реальный режим без verified adapter: incomplete, exit 2.
python3 scripts/run_seaf_review.py --case demo-critical-dependency --mode gigaagent
```

## Что реализовано

- Strict YAML/frontmatter validation: duplicate keys, schema/enums, resource
  limits и типизированные errors.
- Path boundary: absolute/`..`/symlink/hardlink/non-regular/extension/size,
  containment и no-follow чтение.
- `RepositorySnapshotBuilder`: explicit base/head commits, changed paths из Git
  object database, изолированный bounded import/context closure и provenance.
- SEAF-native resolver/adapter: cycle/traversal/symlink/hardlink/duplicate limits,
  fail-closed schema/extension validation и `aga.canonical/v2`.
- Rules-driven dispatcher: behavior определяется `scope`, `check_type`,
  `detect`; unsupported operator и duplicate ID отклоняются.
- PlantUML/Mermaid subset с note/comment filtering, standalone/chained nodes,
  arrow variants и cycle-safe collapse длинных infra paths.
- Exception DSL `all/any/equals/contains/in` + dotted lookup; broad/tautological
  mutation отклоняется.
- Canonical findings и dedup/precedence (`SEAF-004 > PRIN-006`).
- Fitness v2: matching с severity/artifact/defect, FP/FN per severity,
  confusion, precision/recall/blocker recall/outcome/cost, corpus/rules hashes.
- Candidate-only evolution: protected corpus lock, mutation validator, runtime
  policy guard, strict gate, audit log, dry-run publisher и независимый
  validation-only replay. Применение возможно только внешней reviewed
  VCS-транзакцией.
- Append-only review/action feedback, pending precedents, local A2A backend и
  offline fixture LLM adapter. Legacy LLM boundary привязывает finding к
  trusted catalog, changed artifact, разрешающейся location и SHA-256;
  low-confidence major/blocker дают machine-readable incomplete/HITL.
  Network adapter по умолчанию отсутствует, а синхронный adapter
  обязан сам соблюдать `timeout_seconds` (finite, не более 120 с).
  Разрешение сети принимается только как явный boolean.

## Воспроизводимые результаты

Golden corpus содержит 26/26 materialized cases; skipped cases отсутствуют.
Baseline v2.0.0 намеренно содержит один evolution-target false major на `pr-15`:

| Метрика | Baseline | Candidate add_exception |
|---|---:|---:|
| cases evaluated | 26 | 26 |
| expected findings | 20 | 20 |
| precision | 0.9524 | 1.0 |
| recall | 1.0 | 1.0 |
| blocker recall | 1.0 | 1.0 |
| outcome accuracy | 0.9615 | 1.0 |
| exact case accuracy | 0.9615 | 1.0 |
| weighted cost | 2.0 | 0.0 |
| LLM cases evaluated | 0 | 0 |

Candidate exception разрешает только контролируемую batch-выгрузку через
DMZ-шлюз (`pr-15`). Неконтролируемый file-flow `pr-16` продолжает получать
`PRIN-002/major`. Метрики и raw per-case output создаются в
`build/metrics-*.json`; версионный evidence-срез с raw per-case output и
`SHA256SUMS` — в
[`../docs/evidence/snapshots/deterministic-2026-07-15-v2/`](../docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md).
Все 20/20 deterministic rules и 17/17 operator shapes имеют positive и
scope-relevant negative coverage. Baseline до SEAF-изменений:
`182 passed, 10 subtests passed`; актуальный полный результат фиксирует
`make test`, а submission flow — `make demo-offline`.

## Архитектура и safety boundary

```text
immutable Git base/head → bounded SEAF closure → aga.canonical/v2
       → deterministic findings → MCP prepare ─┐
strict semantic JSON from official agent ──────┼→ MCP finalize → HITL verdict
missing/invalid agent ─────────────────────────┘   = incomplete
protected corpus + precedent → mutation guard → fitness gate → build artifacts
                                                    → DryRunPublisher → human
```

Python guard не является process isolation. Внешние branch protection,
CODEOWNERS, identities и Ouroboros/GigaAgent connector описаны в
`docs/AGA-external-enforcement-checklist.md`.

## Структура

```text
tools/aga.py                review engine, parsers, detectors, tool adapter
tools/validation.py         strict schemas and filesystem boundary
tools/{seaf_native,repository_snapshot,seaf_review}.py
tools/{mcp_server,review_service,llm,a2a,feedback,publisher}.py
evolver/{fitness,mutations,policy}.py
scripts/run_review.py       CLI + validated optional LLM aggregation + logging
scripts/run_evolution.py    candidate-only cycle
scripts/record_action.py    append human action / pending precedent
scripts/apply_candidate.py  independent validation-only replay; never writes sources
rules/ · fixtures/ · golden/ · precedents/ · tests/
```

## Критерии Project Results (официальные веса)

| Критерий | Вес | Текущее доказательство / статус |
|---|---:|---|
| Отчёт о результатах MVP | 20% | root `docs/submission/PROJECT-RESULTS.md` + 8-page PDF |
| Применение ГигаАгента | 10% | **external action required**: реальный ГигаАгент не подключён |
| ДЕМО-видео | 30% | сценарий готов; озвученное видео `<180 s` ещё нужно записать |
| Документация и код | 10% | README, Git target commits и package versions готовы; content-addressed supply chain, clean install и public repo не подтверждены |
| Результаты на примерах | 20% | 26 deterministic cases + frozen 16-case agent basket; real denominator 0 |
| Качество материалов | 10% | единая структура материалов; требуется финальный дизайн/вычитка |

Нельзя закрыть локальным кодом: публикацию репозитория, запись видео, реальное
подключение ГигаАгента/Ouroboros и настройки branch protection.

## Зависимости и лицензии

Runtime: только PyYAML 6.0.3 (MIT), version-pinned в `pyproject.toml` и
`requirements.txt`. Wheel/sdist hashes ещё не закреплены. Pytest 9.0.3 —
dev-only. См. `THIRD_PARTY_NOTICES.md`.

## Troubleshooting

- Review завершился exit `1`: для blocker/major это ожидаемая эскалация.
- Exit `2`: смотрите `input_errors`/`analysis_errors`; данные не были approved.
- `LLM mode requires adapter`: используйте offline `--llm-fixture` или
  подключите внешний adapter с явным network flag; raw text не принимается.
- `llm_low_confidence`: trusted major/blocker не достиг порога;
  `hitl_reasons` содержит rule, artifact, confidence и required threshold.
- `fitness_validation`: corpus должен иметь ≥15 materialized cases и совпадать
  с protected snapshot; candidate не может менять error weights.
- `GATE FAIL`: machine-readable reasons находятся в metrics/evolution log.
- `CIRCUIT BREAKER`: доступные кандидаты исчерпаны; автоматическое ослабление
  правил запрещено.

## Полезные проверки

```bash
python3 evolver/fitness.py
python3 -m pytest -q
rg -n 'except Exception|except:' tools evolver scripts
rg -n 'fire\("[A-Z]+-[0-9]+' tools
```

Обе последние команды должны не находить старых fail-open/hardcoded patterns.
