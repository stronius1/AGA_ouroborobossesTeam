# Промпт для модели-исполнителя: доведение `aga-skill` до заявленного уровня

> **Исторический remediation contract.** Его локальные задачи были основой
> версии 2.0.0. Текущая SEAF/Project Results инструкция находится в
> `AGA-SEAF-PROJECT-RESULTS-IMPLEMENTATION-PROMPT.md`.

## Как использовать этот документ

Передай другой модели:

1. весь репозиторий/рабочую папку;
2. этот файл целиком;
3. отчёт `AGA-independent-review-report.md`.

Модель должна **внести изменения в код, тесты и документацию**, а не подготовить ещё один обзор. Работа считается завершённой только после выполнения критериев приёмки и предъявления воспроизводимых команд с exit-кодами.

---

## Роль

Ты — senior Python engineer, security-minded QA и архитектор agentic-систем. Твоя задача — устранить подтверждённые дефекты пакета `aga-skill` и довести реализацию до уровня, который честно соответствует README, `SKILL.md`, `EVOLVER.md` и критериям Sber AI Hack.

Не ограничивайся косметическими изменениями, дополнительными комментариями или ослаблением тестов. Исправляй первопричины.

## Рабочая область

Основной пакет:

```text
aga-skill/
```

Главный отчёт с доказательствами:

```text
AGA-independent-review-report.md
```

Ключевые исходники:

```text
aga-skill/tools/aga.py
aga-skill/scripts/run_review.py
aga-skill/scripts/run_evolution.py
aga-skill/evolver/fitness.py
aga-skill/evolver/permissions.yaml
aga-skill/evolver/EVOLVER.md
aga-skill/SKILL.md
aga-skill/rules/*.yaml
aga-skill/golden/corpus.yaml
aga-skill/tests/test_smoke.py
aga-skill/Makefile
aga-skill/README.md
```

## Обязательный режим работы

1. Сначала прочитай полностью:
   - `AGA-independent-review-report.md`;
   - `aga-skill/README.md`;
   - `aga-skill/SKILL.md`;
   - `aga-skill/evolver/EVOLVER.md`;
   - `aga-skill/evolver/permissions.yaml`;
   - все Python-файлы, правила и текущие тесты.
2. Зафиксируй baseline командами из раздела «Проверка результата».
3. Составь короткий implementation plan с зависимостями между этапами.
4. Затем **реализуй** все этапы ниже.
5. После каждого этапа запускай узкие тесты; в конце — полный набор.
6. Не изменяй существующий ground truth только ради прохождения тестов.
7. Не удаляй и не ослабляй проверки, которые обнаруживают дефекты.
8. Не скрывай исключения через `except Exception: pass`.
9. Не выполняй merge, push, публикацию PR или сетевые вызовы без явного разрешения пользователя. Интеграции должны иметь безопасный dry-run и тестироваться fake/mock-адаптерами.
10. Сохраняй совместимость минимум с Python 3.10+, если репозиторий явно не задаёт иной диапазон.
11. Не добавляй тяжёлую runtime-зависимость, если задача решается stdlib + PyYAML. Новую зависимость обоснуй и зафиксируй.
12. Сохраняй пользовательские и несвязанные изменения в dirty worktree.

## Приоритет источников истины

При конфликте требований используй порядок:

1. Инварианты безопасности: no auto-merge, HITL, обязательный `source_ref`, provenance, защищённый fitness/corpus.
2. Подтверждённые repro из `AGA-independent-review-report.md`.
3. Проверяемые acceptance criteria из этого документа.
4. `SKILL.md`, `EVOLVER.md`, правила и README.

Если документация обещает то, что невозможно реализовать без внешнего Ouroboros/CI, не имитируй готовность. Реализуй локальный контракт и тестовый адаптер, а внешний шаг явно вынеси в отдельный checklist.

---

# Целевое состояние

После доработки должны одновременно выполняться следующие условия:

1. `make demo` проходит end-to-end с exit `0`, показывает blocker-review, evolution, дельту метрик и создаёт проверяемые build-артефакты.
2. PR не может отключить проверки через `kind`, поддельный `changed_files`, absolute path, `..`, symlink или malformed YAML.
3. Любая ошибка входа обрабатывается fail-closed и не приводит к `approve`.
4. Детерминированный движок исполняет правила через валидируемые `scope`, `check_type` и `detect`, а не через жёсткую привязку поведения к `rule_id`.
5. Новое поддерживаемое deterministic-правило действительно меняет результат candidate evaluation.
6. Fitness учитывает severity, артефакт/дефект и не принимает деградацию под видом снижения стоимости.
7. Mutation layer валидирует тип, provenance, допустимые переходы severity/status и неизменность защищённых файлов.
8. Anti-Goodhart не позволяет одному циклу подменить corpus удобным expected и затем оптимизироваться под него.
9. Все 15 corpus cases материализованы либо число исполняемых кейсов честно расширено до не менее 15; метрики показывают фактический denominator.
10. PlantUML/Mermaid edge cases из отчёта покрыты и не дают false approve/false coverage.
11. Дедупликация deterministic + LLM findings реализована в коде.
12. Review/evolution logging образует реальный локальный feedback loop.
13. A2A и публикация PR имеют исполняемые интерфейсы, безопасный local/fake backend и честно описанную внешнюю настройку.
14. README, SKILL и EVOLVER описывают только реально реализованное поведение.
15. Установка зависимостей воспроизводима из чистого checkout: версии закреплены в `pyproject.toml`/requirements/lock-файле, а лицензии новых runtime-зависимостей проверены.

---

# Этап 1. Починить demo-контракт

## Требования

1. Исправь `Makefile`, чтобы штатный exit `1` от blocker-review не останавливал demo.
2. Не маскируй неожиданные exit-коды:
   - `0` — approve/warnings;
   - `1` — ожидаемая эскалация;
   - любой другой код — реальная ошибка и должен остановить demo.
3. `make demo` должен:
   - показать review `pr-12`;
   - подтвердить blocker/escalation;
   - запустить evolution;
   - показать baseline/candidate metrics;
   - проверить наличие `build/evolution-pr.md`, `build/rules.diff`, metrics JSON;
   - завершиться exit `0`.
4. Добавь end-to-end тест demo-контракта.
5. Обнови Quick Start и явно объясни exit-коды `run_review.py`.

## Acceptance criteria

```text
make demo
exit 0
```

В stdout присутствуют:

```text
SEAF-004
GATE PASS
precision
weighted cost
Merge — только человеком
```

---

# Этап 2. Строгая модель входных данных и файловая безопасность

## 2.1. Строгая загрузка YAML

Создай единый безопасный loader/validation layer, например:

```text
aga-skill/tools/validation.py
```

Он должен:

1. Использовать safe loading.
2. Отклонять duplicate mapping keys, включая повторный top-level `cases`.
3. Валидировать, что документ имеет ожидаемый mapping/list type.
4. Валидировать обязательные поля и enum.
5. Возвращать типизированную ошибку с путём и полем.
6. Не превращать YAML parser error в пустой metadata dict.
7. Иметь лимит размера входного файла и разумный лимит YAML aliases/depth, если применимо.

Минимально валидируй:

- PR manifest;
- frontmatter каждого kind;
- SEAF fixture;
- rules;
- severity policy;
- corpus;
- precedents;
- mutations;
- permissions.

## 2.2. Fail-closed review

1. Не доверяй произвольному `kind` из frontmatter.
2. Разреши только известные kind:

```text
system_passport
integration_flow
adr
diagram
out_of_scope
```

3. Сверяй `kind` с путём. Файл под `flows/` не может объявить себя `out_of_scope`.
4. Conflict, unknown kind, missing required field или malformed frontmatter должны формировать структурированный `input_error`.
5. При любом `input_error` итог не может быть `approve`.
6. Для integration flow обязательны как минимум:

```text
id
source
target
pattern
zone
```

7. Для других kind используй documented schema из `golden/README.md` и rules.
8. `changed_files` должен поступать из доверенного diff-provider. Для golden fixture разрешён manifest, но он обязан пройти строгую проверку.
9. Если реальный Git diff недоступен, введи интерфейс `ChangedFilesProvider`:
   - `ManifestChangedFilesProvider` — только для fixtures/tests;
   - `GitChangedFilesProvider` — для локального Git;
   - Ouroboros/VCS adapter — отдельная реализация.

## 2.3. Path containment

Для каждого читаемого пути:

1. Запрети absolute paths.
2. Запрети `..`.
3. Выполни `resolve()`.
4. Проверь, что resolved path находится внутри разрешённого root.
5. Запрети symlink для untrusted PR artifacts либо явно копируй только безопасное содержимое.
6. Учти hardlink escape: либо отклоняй untrusted файлы с неожиданным link count, либо копируй разрешённые artifacts в изолированную staging area и проверяй их там.
7. Проверь обычный файл, расширение и размер.
8. Примени тот же policy к:
   - `review_pr`;
   - `tool_aga_parse_diagram`;
   - `build_llm_payload`;
   - context files;
   - rules/seaf overrides.

## 2.4. Безопасный Markdown и LLM payload

1. Экранируй `|`, newline и опасный HTML в таблицах review.
2. LLM payload должен включать только прошедшие валидацию файлы.
3. Не следуй symlink.
4. Не отправляй payload во внешний сервис по умолчанию.
5. Введи явный network-enabled flag/config.
6. Раздели system instruction и untrusted artifact content.
7. Ответ LLM валидируй как JSON findings schema; raw text не должен напрямую менять verdict.
8. Ограничь timeout и максимальный размер HTTP response.
9. Обрабатывай non-2xx, timeout, invalid JSON, missing fields и oversized response типизированно.
10. Если LLM-проверки обязательны для выбранного режима, отсутствие/ошибка адаптера должны давать `incomplete/error`, а не ложный `approve`.
11. `register()` не должен ловить произвольный `Exception` и молча делать `pass`: ожидаемую несовместимость API отдели от реальной ошибки и выдай диагностируемый результат.

## Обязательные тесты

Добавь тесты с такими смыслами:

```text
test_kind_cannot_opt_out_of_flow_review
test_unknown_kind_fails_closed
test_missing_flow_source_fails_closed
test_missing_flow_target_fails_closed
test_manifest_omission_detected_by_trusted_diff
test_absolute_changed_file_rejected
test_parent_traversal_rejected
test_symlink_artifact_rejected
test_hardlink_escape_rejected_or_isolated
test_llm_payload_does_not_follow_symlink
test_duplicate_yaml_key_rejected
test_yaml_scalar_where_mapping_expected_rejected
test_changed_files_string_rejected
test_missing_file_is_structured_input_error
test_oversized_artifact_rejected
test_markdown_cells_are_escaped
test_llm_http_error_is_typed
test_llm_timeout_is_typed
test_llm_invalid_json_is_rejected
test_llm_oversized_response_is_rejected
test_missing_required_llm_is_not_approve
test_register_failure_is_not_silenced
```

Security-тесты должны использовать только временные каталоги и искусственные файлы. Не читай реальные секреты системы.

---

# Этап 3. Сделать deterministic engine действительно rules-driven

## Требования к архитектуре

Убери бизнес-логику вида:

```python
if meta.get("pattern") == "file":
    fire("PRIN-002", ...)
```

Вместо этого создай dispatcher/registry операторов `detect`. Допускается Python-реестр обработчиков, но выбор правила должен определяться содержимым YAML, а не конкретным `rule_id`.

Пример направления:

```python
DETECTORS = {
    "field_required": check_field_required,
    "field_banned": check_field_banned,
    "required_fields": check_required_fields,
    "field_matches_registry": check_field_matches_registry,
    "systems_must_exist": check_systems_must_exist,
    "endpoint_target_status_forbidden": check_endpoint_target_status,
    "pdn_external_requires_approval": check_pdn_approval,
    "required_sections": check_required_sections,
    "field_in_vocab": check_field_vocab,
    "diagram_parseable": check_diagram_parseable,
    "diagram_edges_labeled": check_diagram_edges_labeled,
    "diagram_no_orphans": check_diagram_no_orphans,
    "flow_present_on_diagram": check_flow_present,
    "edges_covered_by_flows": check_edges_covered,
}
```

Названия можно изменить, но контракт должен быть единым и валидируемым.

## Обязательное поведение

1. `scope` реально фильтрует применимость.
2. `check_type: deterministic` исполняется кодом.
3. `check_type: llm` не исполняется deterministic dispatcher.
4. `hybrid`, если оставлен, имеет явную семантику и тесты.
5. Unsupported detect operator приводит к validation error, а не молчаливому skip.
6. Duplicate rule ID запрещён.
7. У каждого active/candidate rule обязательны:

```text
id
title
statement
severity
scope
check_type
source_ref
provenance
status
```

8. Severity только:

```text
blocker
major
minor
```

9. Новое правило с поддерживаемым detect:
   - исполняется в candidate fitness;
   - создаёт FN/TP/FP по corpus;
   - после явной human-approved activation влияет на обычный review.
10. Определи согласованный lifecycle нового правила:
    - либо `candidate` тестируется через `include_candidates=True`, затем отдельная `activate_rule`;
    - либо active только внутри candidate branch и становится production-active после human merge.

Нельзя оставлять состояние, при котором `add_rule` успешно проходит workflow, но никогда не влияет на review.

## Обязательные contract tests

```text
test_changing_detect_changes_behavior_without_python_change
test_scope_is_enforced
test_llm_rule_is_not_run_deterministically
test_unknown_detect_operator_rejected
test_duplicate_rule_id_rejected
test_new_candidate_rule_runs_in_candidate_fitness
test_new_rule_unknown_to_ground_truth_counts_as_false_positive
test_rule_missing_source_ref_rejected_before_review
test_rule_missing_provenance_rejected_before_review
```

---

# Этап 4. Исправить парсеры, graph traversal, exceptions и дедупликацию

## 4.1. PlantUML

Минимум:

1. Игнорировать содержимое:
   - `note ... end note`;
   - single-line comments;
   - block comments;
   - `skinparam`;
   - прочих non-edge directives.
2. Не считать текст в note реальным edge.
3. Поддержать используемые node declarations и aliases.
4. Отсутствующие `@startuml/@enduml` считать parse error.
5. Непустая диаграмма, из которой не извлечено ни одного ожидаемого элемента, не должна автоматически считаться корректной.

## 4.2. Mermaid

Поддержать и протестировать:

```text
-->
-.-> 
==>
[...]
(...)
{...}
|label|
standalone node declarations
A --> B --> C
```

Standalone nodes должны участвовать в DIAG-002/DIAG-006. Chained edges должны давать все звенья.

## 4.3. `effective_edges`

1. Убери магический cutoff `depth > 4`.
2. Используй cycle-safe traversal через `seen`.
3. Путь с 5, 20 и 50 infra nodes должен обрабатываться корректно.
4. Infra-cycle не должен зависать.
5. Отсутствующий/невалидный `infra` должен иметь явную валидируемую семантику:
   - желательно требовать boolean для каждой SEAF system;
   - либо выдавать diagnostic, а не молча менять смысл графа.

## 4.4. Exception DSL

Расширь и валидируй условия. Минимально нужны:

```yaml
when:
  all:
    - {field: zone, equals: dmz}
    - {field: pattern, equals: file}
    - {field: transfer_mode, equals: batch}
    - {field: gateway_controlled, equals: true}
    - {field: approvals, contains: security}
```

Поддержи:

```text
equals
contains
in
all
any
dotted/nested field lookup
```

Требования:

1. Malformed condition отклоняется при загрузке rules.
2. List matching не зависит от случайного порядка, если оператор семантически означает membership/set.
3. Исключение, эквивалентное полному отключению trigger правила, отклоняется без отдельного committee waiver и positive regression cases.
4. `provenance`, `rationale`, `id`, `added_in` обязательны и непусты.
5. Демо-исключение PRIN-002 должно соответствовать rationale о контролируемом batch-обмене, а не любому file-flow в DMZ.
6. Добавь отрицательный golden case: DMZ file без batch/security/gateway control продолжает получать PRIN-002.

## 4.5. Дедупликация

1. Дедуплицируй `changed_files` и `context_files`.
2. После объединения deterministic и LLM findings выполняй canonical dedup.
3. Введи явную precedence policy, включая:

```text
SEAF-004 > PRIN-006
```

4. Не объединяй разные артефакты/локации, если это самостоятельные нарушения.
5. Fitness и UI должны использовать одну и ту же нормализованную модель finding.

## Обязательные тесты

```text
test_puml_note_edge_is_ignored
test_puml_skinparam_does_not_create_nodes_or_edges
test_mermaid_standalone_nodes_are_parsed
test_mermaid_chained_edges_are_all_parsed
test_mermaid_arrow_variants_and_labels
test_nonempty_unparsed_diagram_fails_closed
test_effective_edges_with_fifty_infra_nodes
test_effective_edges_cycle_terminates
test_missing_infra_flag_is_rejected_or_diagnosed
test_exception_all_condition
test_exception_list_contains_order_independent
test_exception_nested_field
test_malformed_exception_rejected
test_tautological_exception_rejected
test_uncontrolled_dmz_file_flow_is_not_suppressed
test_changed_files_are_deduplicated
test_seaf004_precedes_prin006
```

---

# Этап 5. Перепроектировать fitness и gate

## 5.1. Сопоставление findings

Не своди findings к одному dict `{rule_id: severity}`.

Используй нормализованный ключ, например:

```text
rule_id
severity
artifact
location или canonical_defect
```

Определи документированную matching policy для случаев, когда expected не содержит location.

Severity mismatch должен учитываться как минимум как:

- FN ожидаемой severity;
- FP предсказанной severity;
- отдельная запись severity confusion.

Expected blocker, найденный как major, **не** считается корректно найденным blocker.

## 5.2. Метрики

Считай и публикуй:

```text
cases_evaluated
findings_expected
tp/fp/fn total
tp/fp/fn by severity
precision/recall total
precision/recall by severity
blocker_recall
outcome_accuracy
severity_confusion
weighted_cost
materialized/skipped case IDs
deterministic coverage
llm coverage отдельно
```

Пустой corpus или corpus меньше заданного minimum не должен возвращать «идеальные» метрики. Evaluation должна завершаться validation failure.

Base и candidate должны использовать одну защищённую error-cost policy. Candidate не может уменьшить веса собственных ошибок.

## 5.3. Gate

Все условия должны быть явными и возвращать machine-readable reasons.

Минимальные условия PASS:

1. Нет schema/invariant violations.
2. Blocker recall не падает.
3. Ни один expected blocker не понижен до другой severity.
4. Общий recall не падает.
5. Общая precision не падает либо допускается только явно заданный статистический tolerance.
6. Outcome accuracy не падает.
7. Weighted cost не растёт.
8. `false_blocker` count не растёт независимо от net cost.
9. FP/FN ни одной severity не растут без явно документированного statistical tolerance и отдельного human waiver; blocker/major не имеют tolerance по умолчанию.
10. Есть содержательное строгое улучшение:
    - уменьшился FP/FN;
    - исправился outcome;
    - либо улучшилась severity correctness.
11. Простое понижение severity у того же false finding не считается улучшением.
12. Изменяемое правило имеет positive и negative coverage.

## 5.4. LLM rules

Не смешивай неподтверждённую LLM-оценку с deterministic metrics.

Сделай одно из двух:

1. Реализуй отдельную offline-воспроизводимую LLM evaluation через fixture/fake adapter и отдельные метрики.
2. Либо явно публикуй `llm_cases_evaluated=0` и не заявляй coverage LLM-правил.

Тесты не должны обращаться в сеть.

## Обязательные тесты

```text
test_severity_mismatch_is_not_true_positive
test_blocker_predicted_as_major_reduces_blocker_recall
test_severity_downgrade_does_not_pass_gate
test_recall_drop_does_not_pass_gate
test_false_blocker_increase_never_passes_gate
test_false_major_to_false_minor_is_not_improvement
test_unknown_rule_firing_counts_as_false_positive
test_multiple_same_rule_findings_are_not_collapsed
test_empty_corpus_rejected
test_too_small_corpus_rejected
test_candidate_cannot_change_error_costs
test_llm_metrics_are_separate
```

---

# Этап 6. Mutation validation, SoD и anti-Goodhart

## 6.1. Валидатор мутаций

Введи отдельную модель/валидатор каждого типа:

```text
add_exception
adjust_severity
add_rule
activate_rule
deprecate_rule
add_fewshot
edit_template
refine_wording
```

Если какой-то тип не будет поддерживаться, удали его из документации, SEMVER mapping и заявлений. Нельзя оставлять documented type, который стабильно падает `ValueError`.

Проверяй:

1. Непустой provenance установлен на уровне самой мутации.
2. Ссылка на существующий approved precedent/incident.
3. Rule ID существует или не существует в зависимости от типа.
4. Новый ID уникален.
5. Severity и status допустимы.
6. `add_rule` не может самовольно создать active blocker.
7. Downgrade blocker требует структурированного `committee_decision`, а не обычного override.
8. `deprecate_rule` требует reason, evidence и coverage.
9. Exception не может быть tautological или глобально отключающим без специального approved waiver.
10. `source_ref` и rule provenance обязательны.

## 6.2. Runtime policy guard

Добавь policy guard, который проверяет candidate diff до fitness и до публикации.

Запрещённые изменения для evolver:

```text
evolver/fitness.py
evolver/permissions.yaml
существующие golden expected
SKILL.md security invariants
autonomy.auto_merge
error weights без отдельного major governance change
```

Разрешённые пути и действия должны соответствовать `permissions.yaml`.

Важно: Python guard не является полной SoD-защитой от процесса с полным filesystem access. Поэтому сделай два уровня:

1. Runtime validation внутри приложения.
2. Отдельный внешний checklist/CI policy:
   - protected branch;
   - CODEOWNERS;
   - required checks;
   - отдельная identity/token evolver;
   - запрет merge/approve;
   - review человеком защищённых файлов.

Создай документ:

```text
docs/AGA-external-enforcement-checklist.md
```

Не помечай external SoD как полностью реализованную, пока настройки реально не применены.

## 6.3. Убрать прямое применение evolver

1. Evolve-команда по умолчанию пишет только candidate/build artifacts.
2. Удали `--apply` из evolver либо перенеси применение в отдельную human-only command.
3. Human-only command должна:
   - требовать явное подтверждение;
   - проверять успешный gate и хэши артефактов;
   - не выполнять merge автоматически;
   - быть отделена от evolver role.

## 6.4. Anti-Goodhart

1. Corpus case из прецедента должен существовать в защищённой base revision **до** mutation cycle.
2. `run_evolution` должен отказаться работать, если corpus addition и rule mutation находятся в одном неподтверждённом working diff/commit.
3. Проверяй:
   - exact `origin: precedent:<id>`;
   - materialized directory;
   - manifest/files;
   - approved architect action;
   - immutable existing expected;
   - отсутствие duplicate IDs/keys.
4. Не доверяй одному лишь `materialized: true`.
5. Добавление clean case с `expected.findings: []` допустимо только после отдельного human approval, а не по решению evolver.
6. Baseline и candidate используют один и тот же защищённый corpus snapshot.
7. Храни checksum/revision corpus в metrics artifacts.

## 6.5. Circuit breaker и audit log

1. Реализуй реальные до трёх попыток либо честно убери обещание.
2. Каждая попытка логируется.
3. После лимита возвращается nonzero exit и структурированная причина.
4. Нельзя автоматически перейти к более ослабляющей мутации только ради PASS.

## Обязательные тесты

```text
test_mutation_without_provenance_rejected
test_exception_with_empty_provenance_rejected
test_duplicate_add_rule_rejected
test_active_blocker_add_rule_rejected
test_blocker_downgrade_without_committee_decision_rejected
test_protected_file_change_rejected
test_existing_expected_change_rejected
test_auto_merge_policy_change_rejected
test_same_cycle_corpus_and_mutation_rejected
test_wrong_precedent_origin_rejected
test_unmaterialized_case_rejected
test_duplicate_cases_key_rejected
test_human_apply_is_separate_from_evolver
test_circuit_breaker_logs_all_attempts
```

---

# Этап 7. Материализовать corpus и доказать метрики

## Требования

1. Материализуй все текущие cases `pr-01` … `pr-15`, а не только выставь `materialized: true`.
2. Для каждого case создай реальный каталог:

```text
golden/prs/<id>/meta.yaml
golden/prs/<id>/files/...
```

3. Каждый case должен независимо воспроизводить `expected.findings` и `expected.outcome`.
4. Не копируй один и тот же PR под разными ID без смыслового различия.
5. Добавь дополнительные cases, если 15 недостаточно для:
   - controlled/uncontrolled DMZ exception;
   - Mermaid standalone/chained edges;
   - PlantUML note;
   - multiple blockers/severity mismatch;
   - новое deterministic rule behavior;
   - LLM fixture evaluation.
   - path/manifest и malformed-input regressions, если их удобнее хранить вне unit fixtures.
6. Создай coverage matrix:

```text
rule_id -> positive cases -> negative cases -> execution mode
```

7. Каждый deterministic detect operator должен иметь:
   - хотя бы один positive case;
   - хотя бы один negative case.
8. Отдельно публикуй deterministic и LLM denominator.
9. Исправь арифметическую ошибку «остальные 9» в `golden/README.md`.

## Acceptance criteria

```text
cases_evaluated >= 15
cases_skipped_not_materialized == []
```

Для всех cases:

```text
actual findings == expected findings
actual outcome == expected outcome
```

Если baseline намеренно содержит evolution-target false positive, метрики и версия должны явно указывать, для какой версии правил это ожидается. Smoke test не должен одновременно утверждать противоположный текущему corpus результат без объяснённого versioned corpus.

---

# Этап 8. Замкнуть feedback loop, A2A и LLM aggregation

## 8.1. Review logging

После каждого review безопасно и атомарно записывай:

```text
review_id
timestamp
skill/rules version
input revision/hash
findings
suppressed findings
observations
verdict
escalation
architect_action
```

Не логируй секреты и полный LLM payload.

Добавь отдельную команду/API для записи human action:

```text
accept
override
edit
missed
```

Action должен ссылаться на существующий `review_id` и actor identity.

## 8.2. Precedent generation

1. Approved override/missed action создаёт pending precedent через валидируемый workflow.
2. Evolver читает review log и precedents, а не только вручную подготовленный demo-файл.
3. Приоритет действительно:

```text
missed blocker
false blocker
missed major
noisy minor
```

4. Distillation status и version хранятся отдельными полями:

```yaml
status: distilled
distilled_in: 1.1.0
```

## 8.3. Evolution logging

Пиши `logs/evolution.jsonl`:

```text
cycle_id
precedent
base revision
candidate revision/hash
mutation
attempt
metrics before/after
gate checks
result
generated artifacts
publisher result
```

## 8.4. A2A

Создай исполняемый orchestration interface:

```text
schedule_task
wait_for_task
get_task_result
```

Нужны минимум два backend:

1. Local/fake backend для offline tests.
2. Ouroboros adapter, если реальный API доступен.

Проверь:

1. Диаграммы, SEAF, principles и ADR могут выполняться как отдельные tasks.
2. Parent агрегирует findings.
3. Task failure/timeout не приводит к silent approve.
4. После aggregation выполняется общий dedup и verdict.

Если реальный Ouroboros API недоступен, не выдумывай сигнатуру. Реализуй protocol + fake backend, документируй точную внешнюю точку интеграции и оставь статус `external integration required`.

## 8.5. LLM aggregation

Если реализуется LLM mode:

1. Введи `LLMAdapter` interface.
2. Добавь deterministic fixture adapter для тестов.
3. Валидируй JSON finding schema.
4. Применяй confidence policy из SKILL.
5. Применяй exceptions и provenance.
6. Объединяй с deterministic findings.
7. Выполняй precedence/dedup.
8. Пересчитывай verdict после объединения.
9. Network adapter выключен по умолчанию.

## 8.6. Publisher

Создай `EvolutionPublisher` interface:

1. `DryRunPublisher` — всегда доступен, только артефакты.
2. Git/draft-PR publisher — только явный флаг и настроенная identity.
3. Publisher может создать branch/commit/draft PR, но никогда:
   - merge;
   - approve;
   - push в main.
4. Тестируй publisher mock-объектом без внешних side effects.

## Обязательные тесты

```text
test_review_log_written_atomically
test_architect_action_references_review
test_override_creates_pending_precedent
test_precedent_priority_order
test_distilled_status_schema
test_evolution_log_contains_gate_checks
test_local_a2a_aggregates_results
test_a2a_task_failure_fails_closed
test_llm_fixture_findings_are_validated
test_llm_and_deterministic_findings_are_deduplicated
test_publisher_default_is_dry_run
test_publisher_cannot_merge_or_approve
```

---

# Этап 9. Документация и честность заявлений

После реализации обнови:

```text
README.md
SKILL.md
evolver/EVOLVER.md
evolver/mutations.md
evolver/permissions.yaml
golden/README.md
CHANGELOG.md
VERSION
```

Требования:

1. Quick Start запускается из чистого checkout.
2. Указаны Python version, dependency installation и working directory.
3. Объяснены review exit codes.
4. `make demo` действительно соответствует описанию.
5. Рядом с метриками указан denominator.
6. Deterministic и LLM coverage не смешаны.
7. SoD разделена на:
   - runtime safeguards;
   - CI/repository enforcement;
   - внешние настройки.
8. Не утверждай, что branch/PR/A2A/Ouroboros интеграция работает, если доступен только fake backend.
9. Не утверждай «rules-as-code», пока `detect` не управляет поведением.
10. Приведи status/provenance/version schema к единому виду.
11. Добавь troubleshooting:
    - expected escalation exit;
    - malformed input;
    - отсутствующий external adapter;
    - failed fitness gate;
    - circuit breaker.
12. Зафиксируй зависимости и диапазон Python в `pyproject.toml` либо version-pinned requirements/lock. Для новой parser/schema library укажи причину выбора и лицензию.

---

# Проверка результата

## Baseline перед изменениями

Зафиксируй:

```bash
cd aga-skill
python3 -m pip install pyyaml
python3 tests/test_smoke.py
python3 scripts/run_review.py --pr golden/prs/pr-12
python3 scripts/run_review.py --pr golden/prs/pr-15
python3 evolver/fitness.py
python3 scripts/run_evolution.py --demo
make demo
```

## Финальная проверка

Добавь/используй единый test target. Минимум:

```bash
python3 -m compileall tools evolver scripts tests
python3 tests/test_smoke.py
python3 tests/test_regressions.py
python3 tests/test_security.py
python3 tests/test_fitness.py
python3 tests/test_evolution.py
python3 tests/test_a2a.py
python3 evolver/fitness.py
make test
make demo
```

Если выбран pytest, добавь dev dependency/config и предоставь:

```bash
python3 -m pytest -q
```

Также проверь:

1. Тесты проходят без сети.
2. Повторный прогон даёт те же метрики.
3. Demo не изменяет protected source files.
4. Нет unresolved template placeholders:

```bash
rg -n '\{\{[^}]+\}\}' build
```

5. Нет молча проглоченных ошибок:

```bash
rg -n 'except Exception|except:' tools evolver scripts
```

Каждое оставшееся место объясни и сузь до конкретного exception type.

6. В deterministic engine нет привязки detect behavior к конкретным ID:

```bash
rg -n 'fire\("[A-Z]+-[0-9]+' tools
```

Ожидается отсутствие старой hardcoded dispatch-модели либо обоснованные ссылки только в precedence/config, не в detector logic.

7. Все corpus cases исполняются:

```text
cases_skipped_not_materialized == []
```

8. Fitness artifacts содержат corpus/rules revision hash.
9. `make demo` завершается менее чем за 180 секунд.
10. Сгенерированный diff применим:

```bash
tmp="$(mktemp -d)"
cp -R rules "$tmp/rules"
patch --dry-run -p1 -d "$tmp" < build/rules.diff
```

11. Установка проверена в чистом virtual environment по документированной команде, без незафиксированных глобальных пакетов.

---

# Запрещённые способы «исправления»

Не делай следующее:

1. Не меняй `expected` так, чтобы он совпал с текущими ошибочными predictions.
2. Не помечай пустые/несуществующие PR как materialized.
3. Не заменяй fail-closed behavior на `try/except ... approve`.
4. Не разрешай `kind: out_of_scope` для файлов в известных архитектурных каталогах.
5. Не убирай exit `1` у escalation только ради Make; исправь orchestration.
6. Не объявляй любую severity смену TP только по совпадению rule ID.
7. Не разрешай candidate менять error weights.
8. Не принимай снижение false major до false minor как улучшение.
9. Не добавляй глобальное exception ради прохождения одного golden case.
10. Не считай декларативный YAML permissions runtime enforcement.
11. Не выполняй реальный merge/push/PR без разрешения.
12. Не обращайся к внешнему LLM в тестах.
13. Не заявляй полное закрытие внешнего Ouroboros/CI шага без проверяемого подключения.
14. Не удаляй audit report или regression tests.

---

# Definition of Done

Работа завершена, только если:

1. Для каждого BLOCKER/MAJOR/MINOR из `AGA-independent-review-report.md` есть:
   - кодовый fix либо честно отмеченная внешняя зависимость;
   - regression test;
   - ссылка на изменённые файлы;
   - команда проверки.
2. Все локально реализуемые findings закрыты.
3. `make demo` проходит.
4. Все corpus cases материализованы и совпадают с ground truth.
5. Fitness не пропускает severity downgrade, false blocker growth, tautological exception или protected-file mutation.
6. Review fail-closed на malformed/untrusted input.
7. Rules engine исполняет YAML detect contract.
8. Parser edge cases и длинные infra paths покрыты.
9. Logs и local feedback loop работают.
10. Документация не обещает неподключённые external integrations.
11. Создан `docs/AGA-external-enforcement-checklist.md` для настроек, которые требуют CI/repository/Ouroboros администратора.
12. Финальный отчёт содержит точные test outputs и exit-коды.
13. Финальная карта findings покрывает оба BLOCKER, все MAJOR/MINOR и code-quality notes из аудита; ни один пункт не исчезает без статуса и доказательства.

---

# Формат финального ответа модели-исполнителя

Выдай результат строго в следующем формате:

## 1. Что реализовано

Краткий список функциональных изменений.

## 2. Карта закрытия findings

| Finding из аудита | Fix | Regression test | Статус |
|---|---|---|---|

Допустимые статусы:

```text
fixed
external action required
blocked with evidence
```

Статус `fixed` нельзя ставить без прошедшего теста.

## 3. Изменённые файлы

Список файлов и назначение каждого изменения.

## 4. Проверка

Команды, существенный stdout/stderr и exit-коды.

## 5. Метрики до/после

С фактическим denominator и разделением deterministic/LLM.

## 6. Внешние действия

Только реально необходимые настройки CI, protected branch, CODEOWNERS, identities, Ouroboros API и draft-PR connector.

## 7. Оставшиеся ограничения

Только конкретные, доказанные и не скрытые общими формулировками.

Не завершай работу фразой «осталось добавить тесты» или перечнем рекомендаций вместо реализации. Если локально выполнимый пункт не закрыт, продолжай работу.
