---
name: aga-evolver
version: 2.0.0
description: >
  Candidate-only эволюция правил AGA по подтверждённым действиям архитектора.
  Не активируется внутри review и не имеет merge/push/approve прав.
---

# AGA Evolver — управляемая локальная эволюция

## 0. Реальный контур автономии

Evolver читает approved precedents и создаёт **только candidate artifacts** в
`build/`. Runtime policy задан `permissions.yaml` и проверяется Python guard.
Он не является полноценной SoD-защитой процесса с filesystem access; branch
protection, CODEOWNERS и отдельная identity перечислены во внешнем checklist.

Неподвижные инварианты: `auto_merge: false`, HITL для blocker/major,
`source_ref`, provenance, защищённые fitness/corpus/error weights.

## 1. Входы и приоритет

- append-only `logs/reviews.jsonl` + human action events, которые команда
  `scripts/record_action.py` преобразует в валидируемый pending precedent;
- `precedents/cases/*.md` со статусом `pending` (evolver читает именно этот
  прошедший human-intake слой, а не сырой LLM/review payload);
- `golden/corpus.yaml`, `golden/prs/**`, legacy golden SEAF registry
  `fixtures/seaf.yaml` и human-approved `golden/corpus.lock.json` v2;
- текущие `rules/`.

Приоритет: missed blocker → false blocker → missed major → noisy minor. Один
cycle обрабатывает список предложенных мутаций в этом порядке, максимум три;
если список исчерпан, circuit breaker завершает цикл nonzero и не подбирает
более слабое правило ради PASS.

## 2. Исполняемый цикл

1. Проверить architect action и exact provenance `precedent:<id>`.
2. Проверить lock/hash corpus, immutable existing expected, materialized
   PR fixtures и SEAF registry, затем зафиксировать их точные байты до
   mutation.
3. Посчитать baseline на приватном снимке этих же corpus/PR/SEAF
   байтов (минимум 15 cases).
4. Валидировать mutation schema/provenance/transitions/coverage.
5. Применить одну mutation к `build/candidate-rules/`.
6. Проверить candidate diff runtime policy guard.
7. Посчитать severity-aware fitness с теми же error weights/corpus hash.
8. Строгий gate проверяет recall/precision/outcomes/cost, FP/FN каждой
   severity, false blockers, severity confusion и positive/negative coverage.
   Для `deprecate_rule` coverage mutation-aware: declared case sets exact-
   сверяются с locked baseline false positives целевого правила и его
   scope-relevant non-trigger controls; target не может иметь expected
   findings, а candidate не может менять findings остальных правил.
9. При PASS создать diff, metrics, PR-body, hashes и dry-run publisher result.
10. Записать каждую попытку в `logs/evolution.jsonl`.

Команда:

```bash
python3 scripts/run_evolution.py --demo
```

Она не меняет `rules/`, VERSION или CHANGELOG. Отдельная команда
не доверяет самоподписанному manifest: она повторно строит candidate из
текущего pending-прецедента, пересчитывает metrics/gate и остаётся
validation-only:

```bash
python3 scripts/apply_candidate.py --actor "Имя архитектора"
```

Опции confirmation/apply нет; команда всегда возвращает
`sources_changed: false`, `apply_supported: false` и
`external_apply_required: true`.

Отдельно авторизованный local VCS connector выполняет ту же независимую
validation ещё раз непосредственно перед materialization, связывает её с
exact local Git HEAD и создаёт candidate branch/commit:

```bash
python3 scripts/publish_candidate.py \
  --build build --repository .. --actor "Имя архитектора"
```

Транзакция атомарно содержит только изменённые rule files, `VERSION`, полный
`CHANGELOG.md`, distilled precedent и report/evidence. Она строится в
disposable worktree, поэтому caller HEAD/index/worktree не меняются. У
connector нет remote, push, PR, approve или merge API. Успех честно
возвращает `status: local_candidate_ready`, реальный commit SHA,
`external_side_effects: false` и `draft_pr_url: null`; review обязателен.

Коды выхода: `run_evolution.py` возвращает `0` для готового bundle
(или если pending precedent нет), `1` при непройденном gate и `2` при
невалидных входах. `publish_candidate.py` возвращает `0` только для
`local_candidate_ready` и `2` при validation/policy/Git отказе; до вызова
нужны Python 3, PyYAML, Git с настроенной commit identity и локальный
repository top-level с pending precedent.

## 3. Мутации и versioning

Поддержаны `add_exception`, `adjust_severity`, `add_rule`, `activate_rule`,
`deprecate_rule`; contract и ограничения — в `mutations.md`. Все дают minor
bump. Unsupported mutation возвращает typed error, а не частичное изменение.

## 4. Наблюдаемость и публикация

`logs/evolution.jsonl` содержит cycle/attempt, precedent, revisions/hashes,
mutation, краткие before/after metrics, machine-readable gate checks и result.
Default publisher внутри evolver — `DryRunPublisher`, external side effects
всегда false. Local candidate commit создаёт только отдельный connector после
повторной проверки; сетевой publisher отсутствует.
