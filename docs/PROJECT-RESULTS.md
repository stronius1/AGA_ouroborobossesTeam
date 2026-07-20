# Project Results: AGA + Ouroboros

Дата среза: 20 июля 2026 года. Это канонический текстовый отчёт MVP; при
экспорте в PDF его цифры нельзя менять независимо от
[`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json).

## 1. AS IS: почему ручной governance не масштабируется

Architecture-as-Code PR нужно сверить с SEAF, ADR, диаграммами и
архитектурными принципами. Ручная проверка зависит от загрузки архитектора,
имеет неодинаковую глубину и создаёт повторные итерации из-за комментариев без
точной ссылки на источник.

В Project Proposal приведён не production-замер, а сценарий: 30 PR в неделю по
50 минут дают 25 часов ручного review на блок из четырёх архитекторов. Полная
формула, добавленные допущения и sensitivity находятся в
[`BUSINESS-EFFECT.md`](BUSINESS-EFFECT.md).

## 2. TO BE: что меняет AGA

AGA принимает доверенные immutable `base`/`head` revisions, строит безопасный
snapshot и возвращает интерпретируемое advisory-review:

- детерминированные SEAF, ADR и diagram guardrails;
- semantic review архитектурных принципов через Ouroboros и AGA MCP;
- severity, точный artifact/location, evidence и `source_ref`;
- fail-closed `incomplete`, если данных или надёжности недостаточно;
- локальный candidate patch и повторное review для поддержанного сценария;
- обязательный HITL: `blocker`/`major` не проходят автоматически, merge
  отсутствует.

## 3. Реализованные функции MVP

| Функция | Реализованный результат |
|---|---|
| Architecture-as-Code review | SEAF-native snapshot, deterministic guardrails и semantic boundary |
| Ouroboros orchestration | Реальные review, remediation и re-review tasks с MCP receipts и cost |
| Ремедиация архитектуры | Минимальный patch для `SEAF-004` только по явно заданному `replaced_by` |
| Эволюция правил | Прецедент → candidate mutation → severity-aware fitness → локальный candidate |
| Проверка регрессий | 26 materialized golden cases до и после candidate |
| Unified safety gate | Пять независимых checks; любое падение блокирует результат |
| Evidence | JSON, diff, manifests, SHA-256 и sanitization без secret/raw-provider payload |
| Публикация | Только локальный candidate; push, approve, auto-merge и merge отсутствуют |

## 4. Архитектура решения

```text
Git base/head
    |
    v
trusted snapshot + AGA deterministic guardrails
    |
    +--> AGA MCP prepare --> Ouroboros review --> AGA MCP finalize
                              |
                              v
                    remediation candidate
                              |
                              v
                         re-review

human precedent --> rule mutation --> 26 baseline/candidate fitness tests

architecture gate + rule gate --> unified 5-check gate --> HITL
                                                        --> merge=false
```

Граница доверия важнее конкретной модели: Ouroboros не получает произвольный
filesystem path и не может сам применить или опубликовать candidate. AGA MCP
валидирует revision, schema, evidence и итоговый verdict на стороне trusted
host.

## 5. Demo E2E

Локальный бесплатный сценарий генерирует синтетический граф из 11 узлов и 9
потоков и затем параллельно выполняет два контура.

1. Architecture lane находит `SEAF-004`: поток ведёт в компонент со статусом
   `eliminate`.
2. Remediation меняет только `to: demo.legacy_scoring` на явно объявленный
   `to: demo.scoring_v2`.
3. Re-review подтверждает закрытие finding и отсутствие новых нарушений.
4. Rule lane сравнивает baseline и candidate на всех 26 golden cases.
5. Unified gate проверяет workspace, закрытие `SEAF-004`, 26 candidate
   outcomes, отсутствие rule-regressions и строгое улучшение.
6. Результат сохраняет evidence и требует человеческого review; merge не
   выполняется.

Запуск и проверка:

```bash
make demo-verify
make self-evolution-ui
```

После второй команды интерфейс доступен только на loopback-адресе
`http://127.0.0.1:8090`.

## 6. Результаты на примерах

### Архитектурный finding и remediation

В контролируемом real Ouroboros E2E review-before вернул
`request_changes_escalate`, отдельная remediation task сформировала candidate,
а re-review вернул advisory `approve`. Три task ID и расходы сохранены в
[`ouroboros-self-evolution-v1.json`](evidence/ouroboros-self-evolution-v1.json).
Суммарная зафиксированная стоимость трёх задач — `0.113183 USD`; gate прошёл,
но результат остался локальным candidate с обязательным HITL.

### Эволюция правила и negative control

Baseline ошибочно блокировал согласованный DMZ batch-flow в `pr-15`. Узкое
исключение, выведенное из подтверждённого прецедента, исправило только этот
кейс. Опасный неконтролируемый flow `pr-16` остался заблокированным.

| Результат | Baseline | Candidate |
|---|---:|---:|
| Cases с точным finding-set и outcome | 25/26 | 26/26 |
| Precision | 0.9524 | 1.0 |
| Recall | 1.0 | 1.0 |
| Blocker recall | 1.0 | 1.0 |
| Weighted cost | 2.0 | 0.0 |

Источник: [frozen deterministic snapshot](evidence/snapshots/deterministic-2026-07-15-v2/README.md).

## 7. Метрики и measurement boundary

Одинаковые знаменатели нельзя смешивать в одну «общую точность».

| Измерение | Результат | Что доказывает | Чего не доказывает |
|---|---|---|---|
| Deterministic rule fitness | 25/26 → 26/26 | Узкая mutation улучшает golden-корпус без регрессии | Качество LLM на новых PR |
| Controlled live self-evolution | 3 real tasks, gate PASS, `0.113183 USD` | Ouroboros/MCP review → remediation → re-review работает E2E | Broad semantic release |
| Development-v2 | 48 locked synthetic-public cases; human review `pending`; series `pre_measurement` | Новый strict corpus/scorer и Git materialization готовы к независимой проверке | Model quality или release PASS |
| 16-case fixture | 16/16, release evidence=false | Scorer, corpus и gate plumbing | Качество модели |
| Исторический frozen real run | 10/16; precision/recall/blocker recall `0.50/0.50/0.50`; outcome `0.8125`; unsafe approve `2` | Честный результат старого freeze | Текущую release-готовность |
| Канонический trusted all-case result | `not_run`, 0 cases | PASS-only sentinel не подменён fixture/FAIL | Наличие release PASS |

Старый frozen holdout раскрыт и не может использоваться повторно. Новый
48-case `development-v2` создан и hash-locked, но независимый human review ещё
`pending`, measurement series не frozen и платных прогонов не было. Для нового
release claim нужны независимая проверка ground truth, пять стабильных
development repeats, freeze и новый untouched holdout.

После human review и freeze development stability проверяется ровно на пяти
distinct HMAC-attested captures с неизменными model/prompt/config/selection и
внешним ключом серии.
Бесплатный verifier заново скорит результаты, считает worst-case quality,
approve/non-approve flapping, p95, tokens и cost; team budgets обязательны и
не имеют выдуманных defaults:

Pinned Ouroboros `v6.64.1` main loop не передаёт `temperature`, `top_p` или
`seed`, поэтому sampling determinism не заявляется. Этот факт входит в
secret-free config identity; расхождение повторов не может превратиться в
`approve` через stability gate.

```bash
make verify-development-v2-series \
  DEVELOPMENT_V2_SERIES_INPUTS="repeat-1.json repeat-2.json repeat-3.json repeat-4.json repeat-5.json" \
  DEVELOPMENT_V2_ATTESTATION_KEY_FILE=<external-key-file> \
  DEVELOPMENT_V2_MAX_P95_MS=<team-p95-budget-ms> \
  DEVELOPMENT_V2_MAX_COST_USD=<team-cost-cap-usd>
```

## 8. Safety и ограничения

- Только `synthetic-public` данные разрешены во внешнем model path.
- Raw prompts, provider payloads, credentials и абсолютные локальные пути не
  сохраняются в public evidence.
- Missing context, schema error и invalid evidence должны завершаться
  fail-closed, а не optimistic approve.
- Ремедиация MVP поддерживает один ограниченный паттерн `SEAF-004`; цель
  берётся только из явного `replaced_by`.
- Advisory `approve` не является Bitbucket/GitHub approve и не запускает merge.
- Исторический broad semantic release gate — `FAIL`; нового trusted PASS пока
  нет.
- GitHub Actions закреплены полными commit SHA, базовый Docker image — manifest
  digest, Python wheels для CI/container — SHA-256, apt — датированный Debian
  snapshot. Эти pins проверяет `make project-results-check`; claim не
  распространяется на побитовую воспроизводимость произвольной host-системы.

## 9. Соответствие Project Proposal

Proposal обещал 13 demo PR, 15 systems и auto-approve. Фактический MVP
использует 26 golden cases плюс отдельную 16-case semantic basket, генерирует
11-node demo graph и выдаёт только advisory approve без merge. Это расширение
и изменение границ раскрыто построчно в
[`PROPOSAL-TRACEABILITY.md`](PROPOSAL-TRACEABILITY.md), а не скрыто заменой
цифр.

## 10. Следующие шаги к production

1. Независимо проверить ground truth 48-case `development-v2`, frozen series и
   выполнить пять стабильных development-прогонов.
2. После freeze один раз выполнить новый untouched holdout и получить trusted
   all-case PASS без unsafe approve.
3. Провести Docker build rehearsal на машине с daemon и сохранить build
   provenance; immutable Actions/image/wheel/OS pins уже проверяются локально.
4. Выбрать root license, проверить clean clone в публичном репозитории и опубликовать immutable
   submission commit.
5. Подключить внутренние model/runtime, RBAC, secret store, audit и реальные
   Bitbucket/SEAF endpoints.
6. Измерить production baseline и TCO; не использовать proposal-сценарий как
   фактический ROI.

## 11. Статус артефактов подачи

- Публичный repository URL: **не опубликован**.
- Demo video URL: **не опубликован**.
- Локальный Project Results PDF:
  [`AGA-Ouroboros-Project-Results.pdf`](AGA-Ouroboros-Project-Results.pdf);
  public URL пока **не опубликован**, а этот Markdown остаётся каноническим
  источником.
- Project Proposal: [`Project_Proposal_AGA_SberAIHack.pdf`](../Project_Proposal_AGA_SberAIHack.pdf).
- Презентация: [`AGA-Ouroboros-Project-Results.pptx`](AGA-Ouroboros-Project-Results.pptx),
  редактируемый Markdown: [`PRESENTATION.md`](PRESENTATION.md), speaker outline:
  [`PRESENTATION-OUTLINE.md`](PRESENTATION-OUTLINE.md).
- Сценарий видео: [`DEMO-VIDEO-SCRIPT.md`](DEMO-VIDEO-SCRIPT.md).
