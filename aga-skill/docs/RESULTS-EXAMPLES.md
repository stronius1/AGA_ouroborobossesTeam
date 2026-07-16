# AGA: результаты на 26 тестовых примерах

Срез: **15 июля 2026 года**, получен командой `make demo` на текущем локальном
snapshot. Источники факта:

- [`golden/corpus.yaml`](../golden/corpus.yaml) — ожидания;
- [`metrics-baseline.json`](../../docs/evidence/snapshots/deterministic-2026-07-15-v2/metrics-baseline.json) —
  текущие rules v2.0.0;
- [`metrics-candidate.json`](../../docs/evidence/snapshots/deterministic-2026-07-15-v2/metrics-candidate.json) —
  изолированный candidate v2.1.0;
- [`candidate-manifest.json`](../../docs/evidence/snapshots/deterministic-2026-07-15-v2/candidate-manifest.json) —
  хэши и статус gate.

Важно: candidate **не применён** к исходным rules, не опубликован и не
merged. Таблица «факт» ниже показывает результат изолированного candidate из
изолированного `candidate-rules` в
[`versioned evidence snapshot`](../../docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md),
потому что именно его сравнивает evolution gate.

## Тестовая корзина

Все 26 записей corpus имеют `materialized: true`; пропущенных cases в обоих
metrics-артефактах нет. Корзина содержит:

- 8 ожидаемых `approve` (`pr-01`–`pr-07`, `pr-15`);
- 3 `approve_with_warnings` (`pr-08`, `pr-24`, `pr-26`);
- 15 `request_changes_escalate` (`pr-09`–`pr-14`, `pr-16`–`pr-23`, `pr-25`);
- 20 ожидаемых findings: 4 blocker, 11 major и 5 minor.

## Вход → ожидание → факт → статус

| Case | Вход | Ожидание из corpus | Факт candidate | Статус |
|---|---|---|---|---|
| `pr-01` | `AS-0007-container.puml`, `IF-0031.md`: BI → MDM через API gateway | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-02` | `AS-0014.md`: актуализация описания без изменения интеграций | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-03` | `ADR-0018.md`: полный ADR выбора message broker | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-04` | `IF-0044.md` + context `ADR-0016.md`: CRM → Antifraud через ESB | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-05` | `AS-0007.md`: нейминг и опечатки без смысловых изменений | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-06` | `AS-0006.md`: criticality синхронизирована с SEAF | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-07` | `ADR-0021.md`, `credit-risk-target.mmd`: корректная декомиссия | `approve`, findings нет | `approve`, findings нет | PASS: exact |
| `pr-08` | `hr-payroll.puml`: нет C4 label, узел без кода АС | `DIAG-002 minor`, `DIAG-003 minor`; `approve_with_warnings` | Те же 2 findings; `approve_with_warnings` | PASS: exact |
| `pr-09` | `ADR-0007.md`: нет «Альтернатив», status вне словаря | `ADR-001 major`, `ADR-002 minor`; escalation | Те же 2 findings; `request_changes_escalate` | PASS: exact |
| `pr-10` | `IF-0062.md`, diagram + context flow: заявленный поток отсутствует на диаграмме | `SEAF-006 major`; escalation | `SEAF-006 major`; `request_changes_escalate` | PASS: exact |
| `pr-11` | `AS-0013.md`: owner не совпадает с SEAF registry | `SEAF-002 major`; escalation | `SEAF-002 major`; `request_changes_escalate` | PASS: exact |
| `pr-12` | `IF-0090.md`: новый MQ endpoint имеет `target_status: eliminate` | `SEAF-004 blocker`; escalation | `SEAF-004 blocker`; `request_changes_escalate` | PASS: exact |
| `pr-13` | `IF-0101.md`: ПДн во внешний контур без DPO approval | `PRIN-008 blocker`; escalation | `PRIN-008 blocker`; `request_changes_escalate` | PASS: exact |
| `pr-14` | `IF-0102.md`: endpoint отсутствует в SEAF registry | `SEAF-001 blocker`; escalation | `SEAF-001 blocker`; `request_changes_escalate` | PASS: exact |
| `pr-15` | `IF-0104.md`: DMZ + file + batch + controlled gateway + security approval | `approve`, findings нет | `approve`, finding подавлен узким exception | PASS: exact; baseline имел false `PRIN-002 major` |
| `pr-16` | `IF-0105.md`: неконтролируемый file flow в DMZ | `PRIN-002 major`; escalation | `PRIN-002 major`; `request_changes_escalate` | PASS: negative control не подавлен |
| `pr-17` | `AS-0003.md`: в паспорте АС нет owner | `PRIN-001 major`; escalation | `PRIN-001 major`; `request_changes_escalate` | PASS: exact |
| `pr-18` | `IF-0118.md`: прямое чтение БД антифрода | `PRIN-003 blocker`; escalation | `PRIN-003 blocker`; `request_changes_escalate` | PASS: exact |
| `pr-19` | `AS-0004.md`: criticality не совпадает с SEAF | `SEAF-003 major`; escalation | `SEAF-003 major`; `request_changes_escalate` | PASS: exact |
| `pr-20` | `AS-0007.md`: нет обязательного `target_status` | `SEAF-005 major`; escalation | `SEAF-005 major`; `request_changes_escalate` | PASS: exact |
| `pr-21` | `broken-context.puml`: нет `@enduml` | `DIAG-001 major`; escalation | `DIAG-001 major`; `request_changes_escalate` | PASS: exact |
| `pr-22` | `unlabeled-edge.puml`: связь без протокола/IF-ID | `DIAG-004 major`; escalation | `DIAG-004 major`; `request_changes_escalate` | PASS: exact |
| `pr-23` | `extra-edge.puml` + context flow: лишняя связь без flow | `DIAG-005 major`; escalation | `DIAG-005 major`; `request_changes_escalate` | PASS: exact |
| `pr-24` | `orphan-node.puml`: изолированный узел AS-0007 | `DIAG-006 minor`; warnings | `DIAG-006 minor`; `approve_with_warnings` | PASS: exact |
| `pr-25` | `ADR-0025.md`: systems содержит отсутствующую AS-0099 | `ADR-003 major`; escalation | `ADR-003 major`; `request_changes_escalate` | PASS: exact |
| `pr-26` | `ADR-0026.md`: нет date и author | `ADR-004 minor`; warnings | `ADR-004 minor`; `approve_with_warnings` | PASS: exact |

`PASS: exact` означает одновременно точное совпадение набора ожидаемых
findings с учётом severity и совпадение итогового verdict. Для полей
`artifact`, `location` и `canonical_defect` сравнение становится обязательным,
если они заданы в ground truth.

## Итоговые метрики

| Метрика | Baseline rules | Candidate rules | Дельта |
|---|---:|---:|---:|
| Cases evaluated | 26 | 26 | 0 |
| Cases skipped | 0 | 0 | 0 |
| Expected findings | 20 | 20 | 0 |
| Predicted findings | 21 | 20 | −1 |
| TP | 20 | 20 | 0 |
| FP | 1 major | 0 | −1 |
| FN | 0 | 0 | 0 |
| Precision | 0.9524 | 1.0 | +0.0476 |
| Recall | 1.0 | 1.0 | 0 |
| Blocker recall | 1.0 | 1.0 | 0 |
| Outcome accuracy | 0.9615 | 1.0 | +0.0385 |
| Exact case accuracy | 0.9615 | 1.0 | +0.0385 |
| Weighted cost | 2.0 | 0.0 | −2.0 |

Единственная baseline-ошибка — false major `PRIN-002` на `pr-15`. Candidate
добавляет узкое исключение и устраняет её. `pr-16` подтверждает, что
неконтролируемый DMZ file flow по-прежнему блокируется major finding.

## Методика расчёта

### Единица сравнения

Ожидаемый и предсказанный finding сопоставляются по:

1. `rule_id`;
2. точной severity;
3. `artifact`, `location`, `canonical_defect`, если соответствующее поле явно
   задано в ground truth.

Совпадение rule ID при другой severity не считается TP: это одновременно FN
ожидаемой severity и FP предсказанной severity и отдельно попадает в
`severity_confusion`.

### Формулы

```text
precision = TP / (TP + FP)
recall = TP / (TP + FN)
blocker_recall = TP_blocker / (TP_blocker + FN_blocker)
outcome_accuracy = cases с верным verdict / все обработанные cases
exact_case_accuracy = cases с точными findings и verdict / все cases
```

Если denominator равен нулю, реализация возвращает `1.0`; поэтому метрики
нужно читать вместе с `findings_expected`, разбивкой severity и фактическим
denominator.

Weighted cost использует защищённые веса из severity policy:

```text
10 × FN_blocker
+ 5 × FN_major
+ 1 × FN_minor
+ 3 × FP_blocker
+ 2 × FP_major
+ 0.5 × FP_minor
```

Baseline и candidate имеют одинаковые:

- `corpus_revision`:
  `0edeb450db5f7ffbf2aa5c57bbb608b2375c04ee0977b8d1b641e3d6751fbd3b`;
- `fixtures_revision`:
  `46e0a8cd6accdd0b173f5711600c0f256f065f863ae7f077d3a6f53201d5f6d3`;
- `error_costs_hash`:
  `e863856d6dbb9607cf6fe30aa88b8a5ef8b01325c7ff3c90aa419a29e17ac809`.

Это подтверждает, что сравнение выполнено на одном приватном снимке
corpus/PR fixtures/SEAF registry и с одними весами ошибок. Комбинированный
revision включает golden tree
`275ac7ee0a1e49fa95002838ab51b7c81a2f9b1410976f3a7df303c61759df96` и
`fixtures/seaf.yaml`
`7f15e64b83a76b48d77561254b3b01952c565e03dbbf74db4a62f17be1d14e71`.

## Воспроизведение

Из каталога `aga-skill`:

```bash
python3 -m pip install -r requirements-dev.txt
make demo
make test
```

Exact pins зафиксированы, но установка в пустой venv в этой среде не
проверена из-за запрета сети и отсутствия полного local wheel cache.
Приведённые результаты получены в текущем уже подготовленном окружении.

`make demo` заново создаёт игнорируемые runtime-артефакты в `build/`. Проверяемый
срез этой серии хранится в
`docs/evidence/snapshots/deterministic-2026-07-15-v2/` и защищён `SHA256SUMS`:

```text
metrics-baseline.json
metrics-candidate.json
candidate-rules/
rules.diff
evolution-pr.md
candidate-manifest.json
publisher-result.json
```

Последняя локальная проверка 15 июля 2026 года:

```text
make demo: exit 0, real 1.54 s
current project-owned pytest: 381 passed, 32 subtests passed
```

## Что эти результаты не доказывают

- Корзина состоит из 26 синтетических fixtures и не является статистически
  репрезентативной выборкой production PR.
- Candidate оценён на защищённом golden corpus, но отдельного независимого
  holdout сейчас нет.
- Все 20/20 deterministic rules и 17/17 operator shapes имеют
  positive и negative coverage в текущей корзине; это не заменяет
  независимый production holdout.
- Четыре LLM rules не входят в эти показатели:
  `llm_coverage.cases_evaluated = 0` и
  `findings_evaluated = 0` в обоих metrics-артефактах.
- Реальный ГигаАгент не подключён; качество его ответов не измерялось.
- Значения candidate не являются production-метриками до человеческого review
  и отдельного применения candidate.
