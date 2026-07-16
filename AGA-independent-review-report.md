# Независимая проверка пакета `aga-skill`

> **Исторический документ.** Findings относятся к pre-remediation snapshot;
> актуальное состояние и доказательства находятся в `README.md` и
> `docs/submission/PROJECT-RESULTS.md`.

Дата проверки: 2026-07-15

## 1. TL;DR

8/8 smoke-тестов проходят; штатные `pr-12`, `pr-15` и offline evolution воспроизводятся.  
Заявленные метрики совпали: precision `0.8333 → 1.0`, weighted cost `2.0 → 0.0`.  
Текущие правила соответствуют corpus только на 4/5 материализованных PR; кандидат — на 5/5.  
`make demo` не работает: ожидаемый exit `1` от blocker-review останавливает Make до evolution.  
Blocker-проверку можно обойти, указав во frontmatter `kind: out_of_scope`; результат — `approve`.  
Fitness и mutation layer пропускают понижение severity, полное отключение правила и нарушения provenance; SoD не исполняется runtime.  
Hackathon-готовность: **5/10** — happy path демонстрируем, но ключевые заявления о безопасной самоэволюции и метриках пока не подтверждаются кодом.

## 2. Repro log

### Baseline

```text
$ cd /Users/podsechka/Хаккатон/aga-skill
$ python3 -m pip install pyyaml
Requirement already satisfied: pyyaml in /Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages (6.0.3)
exit 0
```

```text
$ python3 tests/test_smoke.py
  PASS test_evolution_mutation_and_gate
  PASS test_pr01_clean_approve
  PASS test_pr08_minor_warnings
  PASS test_pr09_adr_major
  PASS test_pr12_blocker
  PASS test_pr15_false_positive_on_v1
  PASS test_rules_load
  PASS test_seaf_fixture

8/8 passed
exit 0
```

### `pr-12`

```text
$ python3 scripts/run_review.py --pr golden/prs/pr-12
## 🤖 AGA review · skill v1.0.0

**PR:** pr-12 — Новый MQ-поток из АБС в выводимое ДБО ЮЛ
**Вердикт:** 🛑 Request changes + эскалация архитектору

### Замечания

| Правило | Severity | Артефакт | Что не так | Основание |
|---|---|---|---|---|
| SEAF-004 | blocker | `flows/IF-0090.md` | конечная точка с target_status=eliminate: AS-0011 | SEAF-МЕТАМОДЕЛЬ v2.1 §5.4 (TIME) |

### Подавлено исключениями
—

### Не проверялось детерминированно (LLM-правила)
PRIN-004, PRIN-005, PRIN-006, PRIN-007

---
*AGA — advisory-агент: auto-merge отключён, blocker/major эскалируются
дежурному архитектору. Не согласны с выводом — переопределите с обоснованием:
это станет прецедентом и улучшит правила (см. precedents/README.md).*

exit 1
```

Exit `1` штатный: `scripts/run_review.py:111` возвращает его для эскалации.

### `pr-15`

```text
$ python3 scripts/run_review.py --pr golden/prs/pr-15
## 🤖 AGA review · skill v1.0.0

**PR:** pr-15 — Файловый batch-обмен в DMZ-сегменте
**Вердикт:** 🛑 Request changes + эскалация архитектору

### Замечания

| Правило | Severity | Артефакт | Что не так | Основание |
|---|---|---|---|---|
| PRIN-002 | major | `flows/IF-0104.md` | pattern: file — файловый обмен вне утверждённых паттернов | АРХ-ПРИНЦИПЫ §4.2 |

### Подавлено исключениями
—

### Не проверялось детерминированно (LLM-правила)
PRIN-004, PRIN-005, PRIN-006, PRIN-007

---
*AGA — advisory-агент: auto-merge отключён, blocker/major эскалируются
дежурному архитектору. Не согласны с выводом — переопределите с обоснованием:
это станет прецедентом и улучшит правила (см. precedents/README.md).*

exit 1
```

### Evolution demo

```text
$ python3 scripts/run_evolution.py --demo
AGA Evolver · skill v1.0.0
==================================================
[1/6] Прецедент: 0001 (0001-dmz-file-exchange.md), architect_action=override
[2/6] Anti-Goodhart OK: кейс pr-15 в корпусе (origin: precedent:0001)
[3/6] Baseline: cost=2.0, precision=0.8333, blocker_recall=1.0, outcome_acc=0.8
[4/6] Попытка 1: мутация add_exception → PRIN-002 (v1.0.0 → v1.1.0)
[5/6] Candidate: cost=0.0, precision=1.0 → GATE PASS
[6/6] Артефакты PR готовы в build/: evolution-pr.md, rules.diff, CHANGELOG-entry.md, metrics-*.json
      Ветка: skill/evolution-2026-07-15-PRIN-002
      Merge — только человеком.
exit 0
```

Метрики совпали с заявленными.

Ручная арифметика:

- Ground truth материализованных кейсов: `pr-08` — 2 findings, `pr-09` — 2, `pr-12` — 1; всего 5.
- Baseline: `TP=5`, лишний `PRIN-002/major` на `pr-15`, поэтому `FP_major=1`, `FN=0`.
- Precision: `5 / 6 = 0.8333`.
- Recall: `5 / 5 = 1.0`.
- Blocker recall: `1 / 1 = 1.0`.
- Outcome accuracy: `4 / 5 = 0.8`.
- Cost: `1 false major × 2.0 = 2.0`.
- Candidate убирает FP: precision/outcome accuracy `1.0`, cost `0.0`.

### Сверка с corpus

```text
$ python3 <harness calling review_pr for materialized cases>
pr-01 findings_match=True  outcome_match=True
pr-08 findings_match=True  outcome_match=True
pr-09 findings_match=True  outcome_match=True
pr-12 findings_match=True  outcome_match=True
pr-15 findings_match=False outcome_match=False
exit 0
```

На `build/candidate-rules` все пять кейсов совпадают. Расхождение `pr-15` намеренно используется для evolution demo, но `8/8 smoke` не означает соответствие текущего v1.0.0 всему materialized ground truth.

### Артефакты evolution

```text
$ rg -n '\{\{' build/evolution-pr.md build/rules.diff
<нет вывода>
```

```text
$ patch --dry-run -p1 -d "$tmp" < build/rules.diff
patching file 'rules/principles.yaml'
exit 0
```

`build/rules.diff` — применимый минимальный unified diff. `build/evolution-pr.md` соответствует шаблону, placeholders заменены, таблица метрик и четыре gate-checkbox заполнены. При этом реальная Git-ветка или PR не создаются: это только текстовые артефакты и имя ветки.

### Edge cases

```text
empty .puml                         -> None
PlantUML без @enduml                -> None
skinparam + обычный note            -> разбираются
строка "A --> B" внутри note        -> ошибочно становится реальным edge
Mermaid -->, -.->, ==>              -> разбираются
Mermaid [...], (...), {...}         -> разбираются
Mermaid -->|label|                  -> label разбирается
Mermaid standalone nodes            -> nodes={}, edges=[]
Mermaid A --> B --> C               -> только A→B
4 infra hops                        -> effective edge найден
5 infra hops                        -> effective edge потерян
infra-cycle                         -> не зависает
infra flag отсутствует              -> узел перестаёт быть прозрачным
```

Exception matcher:

```text
scalar equality                     -> match
exact list equality                 -> match
тот же список в другом порядке      -> no match
list containment                    -> no match
dotted nested field                 -> no match
logical all/any                     -> no match
```

Демо-исключение `zone == dmz` также совпадает для `pattern=file`, `batch=false`, `approvals=[]`: заявленное исключение для контролируемого batch-файлообмена фактически подавляет любой file-flow в DMZ.

### Demo target

```text
$ /usr/bin/time -p make demo
python3 scripts/run_review.py --pr golden/prs/pr-12
...SEAF-004 blocker...
make: *** [review] Error 1
real 0.08
user 0.05
sys 0.01
exit 2
```

Evolution не запускается. Отдельные команды выполняются значительно быстрее трёх минут, но заявленный `make demo` требует ручного обхода exit-кода.

## 3. Findings

### BLOCKER

- **[BLOCKER] Проверяемый артефакт может сам отключить для себя ревью**

  - Что не так: `classify()` в `tools/aga.py:147` без валидации доверяет `kind` из frontmatter. Список файлов также берётся из `meta.yaml`, а не из доверенного Git diff (`tools/aga.py:193`).
  - Как воспроизвести: заменить в `pr-12/files/flows/IF-0090.md` `kind: integration_flow` на `kind: out_of_scope`. Результат: `findings=[]`, `verdict=approve`, exit `0`. Поток без `source` и `target` также получает `approve`.
  - Влияние: автор PR может скрыть настоящий `SEAF-004/blocker` одной строкой metadata либо не включить файл в `changed_files`. Это полный fail-open governance bypass.
  - Предложение фикса: получать changed files из доверенного VCS/API; валидировать допустимые kind и согласованность kind↔path; обязательные поля проверять до правил; любой конфликт/ошибка входа должен давать `input_error/request_changes`, а не `approve`.

- **[BLOCKER] Fitness-гейт вознаграждает ослабление правил и пропускает нарушение инвариантов**

  - Что не так: TP/FP/FN сопоставляются только по `rule_id`, а не по `(rule_id, severity)` (`evolver/fitness.py:47`). Gate не проверяет precision или общий recall (`evolver/fitness.py:87`). `apply_mutation` не валидирует provenance, уникальность ID, максимальную severity или ширину исключений.
  - Как воспроизвести: `adjust_severity PRIN-002 major→minor` даёт:

    ```text
    precision          0.8333 -> 0.8333
    fp_total           1      -> 1
    outcome_accuracy   0.8    -> 0.8
    weighted_cost      2.0    -> 0.5
    GATE PASS
    ```

    Исключение `when: {field: pattern, equals: file}` полностью отключает PRIN-002, проходит gate `2.0→0.0` даже с пустым `provenance`.
  - Влияние: evolution может «улучшить» метрику понижением severity или эквивалентом `deprecate_rule`, не исправив false finding. Expected blocker, предсказанный как major, всё равно считается найденным blocker; при наличии другого major/blocker outcome accuracy тоже не заметит деградацию.
  - Предложение фикса: severity confusion matrix; mismatch считать FN ожидаемой severity и FP предсказанной; отдельно запретить падение precision/recall и рост FP каждой severity; валидировать mutation schema, provenance, уникальные ID и positive cases каждого изменяемого правила.

### MAJOR

- **[MAJOR] YAML `detect/scope/check_type` не управляют движком; `add_rule` поведенчески не реализован**

  - Что не так: проверки захардкожены вызовами `fire("PRIN-002", ...)` в `tools/aga.py:239`. В Python вообще нет чтения поля `detect`.
  - Как воспроизвести: изменить у PRIN-002 `detect` на запрет `mq`, `scope` на `adr`, `check_type` на `llm` и добавить активный PRIN-009 с `detect: banned[file]`. `pr-15` всё равно получает PRIN-002; PRIN-002 одновременно попадает в `skipped_llm_rules`; PRIN-009 не срабатывает.
  - Влияние: правила являются конфигурацией сообщений/severity/exceptions, но не rules-as-code в заявленном смысле. Новый `rule_id`, отсутствующий в corpus, по умолчанию имеет `status: candidate` и не считается FP; даже принудительно active он не исполняется. Теоретически неизвестный predicted ID fitness посчитал бы FP, но текущий движок не способен его породить.
  - Предложение фикса: реализовать валидируемый dispatcher/DSL по `scope`, `check_type`, `detect`; либо убрать `add_rule` из заявленных возможностей и явно назвать движок code-bound.

- **[MAJOR] SoD и anti-Goodhart существуют только как декларация**

  - Что не так: `permissions.yaml` нигде не загружается и не исполняется. `run_evolution.py:243` через `--apply` напрямую переписывает `rules/`, `VERSION`, `CHANGELOG` и precedent. Anti-Goodhart проверяет лишь совпадение ID и `materialized: true`, но не `origin` и не независимость `expected` (`run_evolution.py:184`).
  - Как воспроизвести: PyYAML разрешает дописать второй top-level ключ `cases:`; последний молча заменяет первый:

    ```text
    original_cases=15
    after_append_duplicate_cases=0
    ```

    При append списка только с удобным `pr-15` baseline оценивает один кейс, blocker recall по отсутствующим blockers становится `1.0`, а отключающая PRIN-002 мутация проходит gate.
  - Влияние: даже семантика разрешения `golden/corpus.yaml#append` не защищает экзамен. Прямая модификация fitness или массы исключений также не блокируется внутри пакета.
  - Предложение фикса: enforcement на уровне защищённой ветки/CI и отдельной identity; CODEOWNERS для fitness/corpus/permissions; corpus-append через типизированный API с duplicate-key rejection; baseline брать из защищённого commit; удалить `--apply` из роли evolver.

- **[MAJOR] Заявленный `make demo` завершается до evolution**

  - Что не так: `Makefile:2` считает штатный exit `1` blocker-review ошибкой.
  - Как воспроизвести: `make demo` → `make: *** [review] Error 1`, итоговый exit `2`; evolution stdout отсутствует.
  - Влияние: критерий «демо ≤3 мин» проваливается не по времени, а по orchestration. Во время защиты нужен ручной обход.
  - Предложение фикса: явно принять exit `1` как ожидаемый verdict, затем запускать evolution; добавить тест, который проверяет полный `make demo` и финальные артефакты.

- **[MAJOR] Парсеры диаграмм создают ложные связи и пропускают валидные узлы**

  - Что не так: regex PlantUML применяется ко всему тексту, включая `note ... end note` (`tools/aga.py:71`). Mermaid nodes создаются только при совпадении edge-regex (`tools/aga.py:103`).
  - Как воспроизвести: строка `A --> B : prose only` внутри PlantUML note становится edge и скрывает SEAF-006. Валидная Mermaid-диаграмма с C4 marker и standalone A/B nodes возвращает `nodes={}`, `edges=[]`, `findings=[]`.
  - Влияние: возможны false negative по SEAF-006/DIAG-002/DIAG-006 и ложное подтверждение интеграции.
  - Предложение фикса: AST/грамматический parser; минимум — удалить comments/note blocks перед edge parsing и отдельно разбирать node declarations/chained edges. Добавить golden Mermaid и note-based negative fixtures.

- **[MAJOR] Path traversal и symlink позволяют читать и отправлять файлы вне PR**

  - Что не так: `(files_root / rel).read_text()` не проверяет containment (`tools/aga.py:199`). `build_llm_payload` рекурсивно читает symlink-файлы (`run_review.py:81`), после чего payload может уйти в OpenRouter.
  - Как воспроизвести: `changed_files: ../../pr-12/files/flows/IF-0090.md` в метаданных `pr-15` реально читает файл соседнего PR и выдаёт SEAF-004. Symlink внутри `files/` на внешний файл появляется в LLM payload целиком.
  - Влияние: произвольное чтение доступных процессу файлов; при `--mode llm` и настроенном ключе — передача локального содержимого внешнему сервису.
  - Предложение фикса: `resolve()` и проверка `is_relative_to(files_root.resolve())`; запрет absolute/`..`/symlink; allowlist расширений и лимиты размера; явное разрешение на внешний LLM.

- **[MAJOR] Цикл самоэволюции не замкнут, A2A и публикация PR отсутствуют в коде**

  - Что не так: `run_review.py` не пишет `logs/reviews.jsonl`; evolution не преобразует architect actions в precedents; `run_evolution.py` не создаёт Git branch/commit/PR и не пишет `logs/evolution.jsonl`. В Python нет `schedule_task`, `wait_for_task` или `get_task_result`.
  - Как воспроизвести:

    ```text
    $ rg 'schedule_task|wait_for_task|get_task_result|open_pull_request|reviews.jsonl|evolution.jsonl' --glob '*.py'
    ./evolver/fitness.py:10: ...permissions.yaml...
    ```

    Мутации `add_fewshot`, `edit_template`, `refine_wording` завершаются `ValueError`.
  - Влияние: реализован offline трансформатор одного вручную подготовленного прецедента, а не автономный feedback loop Ouroboros. A2A §7 — только таблица.
  - Предложение фикса: до защиты либо реализовать один настоящий путь review-log→architect action→precedent→candidate→PR, либо сузить pitch до «offline prototype rule evolution».

- **[MAJOR] Заявление о метриках ≥10 примеров не подтверждается фактическим denominator**

  - Что не так: `fitness.py` оценивает только 5 materialized cases и пропускает 10; `README.md:66` представляет метрики как закрывающие критерий ≥10. В `golden/README.md` дополнительно написано «остальные 9», хотя осталось 10.
  - Как воспроизвести: `python3 evolver/fitness.py` → `cases_evaluated: 5`, список `cases_skipped_not_materialized` содержит 10 ID.
  - Влияние: с точки зрения жюри 15 строк сценариев не равны 15 обработанным примерам. Все materialized expected findings относятся к deterministic rules; качество четырёх LLM-правил fitness не измеряет. Если добавить ожидаемый LLM finding, текущий review всегда даст FN.
  - Предложение фикса: материализовать минимум 10 разнородных PR и публиковать denominator рядом с каждой метрикой; LLM-метрики считать отдельным воспроизводимым прогоном либо честно исключить из measured scope.

### MINOR

- **[MINOR] Дедупликация SEAF-004 vs PRIN-006 не реализована**

  - Что не так: `fire()` безусловно добавляет finding (`tools/aga.py:221`); precedence/dedup pass отсутствует.
  - Как воспроизвести: повторить `flows/IF-0090.md` дважды в `changed_files` — получится два одинаковых SEAF-004. В штатном `pr-12` PRIN-006 отсутствует только потому, что он LLM-only, имеет другой scope и пропускается.
  - Влияние: после будущего объединения deterministic и LLM результатов обещанный инвариант не гарантирован; сейчас возможен comment spam.
  - Предложение фикса: дедуплицировать manifest и findings по canonical defect key; завести явную precedence map `SEAF-004 > PRIN-006`.

- **[MINOR] `effective_edges` молча обрезает длинные инфраструктурные пути**

  - Что не так: магическая граница `depth > 4` в `tools/aga.py:136`.
  - Как воспроизвести: четыре infra hops дают effective edge, пять — пустой результат. Циклы при этом уже безопасно ограничены `seen`.
  - Влияние: ложные SEAF-006/DIAG-005 на длинных маршрутах. Отсутствующий `infra` также молча делает шлюз непрозрачной бизнес-системой.
  - Предложение фикса: обходить infra-граф до исчерпания `seen`; если нужен лимит — конфигурировать его и возвращать явное incomplete-analysis warning.

## 4. Code-quality notes

- `yaml.safe_load` защищает от конструирования Python-объектов, но схемы, типы, duplicate keys и размеры не валидируются.
- Невалидный `meta.yaml` даёт необработанный `ParserError`; отсутствующий changed file — `FileNotFoundError`; YAML scalar — `AttributeError`; строка вместо `changed_files` — `TypeError`.
- `parse_frontmatter()` молча превращает YAML-error в `{}`, что создаёт fail-open поведение вместо явного input finding.
- `exception_matches` поддерживает только одно точное равенство. Списки чувствительны к порядку, nested/all/any/contains отсутствуют; malformed selector может дать `TypeError`.
- `register()` ловит любой `Exception` и делает `pass`: ожидаемое несовпадение API неотличимо от реального дефекта регистрации.
- `urlopen(... # noqa: S310)` для константного HTTPS URL само по себе оправдано: SSRF через URL здесь нет. Проблема в отсутствии HTTP/schema/response-size handling, trust boundary для payload и парсинга model output.
- Markdown title/evidence/artifact не экранируются: `|`, newline и HTML из PR способны сломать review table.
- `find_pending_precedent()` сортирует имена файлов, а не заявленный приоритет missed blocker/false blocker.
- `status: distilled (1.1.0)` не соответствует документированному точному статусу `distilled`; версию лучше хранить отдельным полем.
- Восьмой smoke-тест — это не восьмой PR. Тесты покрывают 5 golden cases, загрузку rules/SEAF и один happy-path `add_exception`; не покрывают Mermaid, PlantUML notes, malformed YAML, traversal, дедуп, graph limits, severity mismatch, остальные mutations, anti-Goodhart, SoD, A2A, LLM payload и `make demo`.

## 5. Design & concept observations

Реализованная «трёхконтурность»:

- **Архитектура банка:** только читается и проверяется в виде локальных snapshots; не эволюционирует.
- **Методы governance:** реально меняются exceptions/severity/status существующих hardcoded rule IDs. Новое правило не получает исполняемого поведения.
- **Агент:** Python-код не эволюционирует; A2A, scheduling, runtime permissions и Ouroboros PR workflow отсутствуют.

Фраза «AGA делает с методологией то, что Ouroboros делает со своим кодом» реализована как метафора на уровне `candidate copy → fitness → diff → Markdown PR body → human checklist`. Ветки, PR, независимые права, автоматический feedback ingestion и закрытый learning loop не реализованы.

| Критерий | Наблюдение |
|---|---|
| Работоспособность, 30% | Offline deterministic happy path и одна exception mutation работают; generic rules, LLM aggregation и Ouroboros workflow — нет |
| Демо, 30% | Отдельные команды укладываются в секунды; `make demo` падает до evolution |
| Документация, 15% | Quick start действительно содержит 5 команд, но шаг 2 возвращает неожиданный для shell exit `1`; denominator метрик не объяснён рядом с результатом |
| Метрики, 15% | Фактически 5 обработанных PR, 5 TP и один FP; 10 сценариев не исполняются |
| Безопасность, 5% | `auto_merge: false` и escalation verdict работают декларативно; SoD, provenance и mutation constraints runtime не enforced |
| Стабильность, 5% | Happy path стабилен; malformed input, traversal, parser edge cases и schema drift не контролируются |

## 6. Recommendations

1. **Починить `make demo` и добавить один end-to-end demo test** — **0.5–1 час**. Принимать exit `1` как ожидаемый blocker verdict и проверять, что evolution/artifacts всё равно созданы.
2. **Закрыть fail-open входы и файловые границы** — **4–6 часов**. Доверенный diff, schema validation, kind/path consistency, required fields, containment/symlink protection.
3. **Усилить fitness и mutation gate** — **8–12 часов**. Severity-aware scoring, per-severity guards, unique IDs, provenance/source_ref validation, ограничение exceptions, защищённый corpus без duplicate keys.
4. **Сделать rules engine действительно rules-driven и расширить golden до ≥10 PR** — **12–20 часов**. Dispatcher по `detect/scope/check_type`, Mermaid/note fixtures, positive case для каждого эволюционируемого правила.
5. **Перед защитой либо замкнуть один реальный Ouroboros workflow, либо сузить pitch** — **8–16 часов**. Минимум: review log → architect action → precedent → protected candidate → настоящий draft PR; A2A заявлять только после исполняемого `schedule_task`.
