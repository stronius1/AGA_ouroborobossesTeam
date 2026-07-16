# Coverage matrix golden-корпуса

Матрица описывает ground truth 26 материализованных кейсов `pr-01`…`pr-26`.
Positive case — кейс, где finding правила явно присутствует в
`expected.findings`. Negative case — релевантный артефакт проходит
проверку, и finding отсутствует в ground truth.

`pr-15` — negative case для `PRIN-002`: контролируемый batch-обмен в
DMZ. Rules v2.0.0 без узкого exception намеренно дают на нём evolution-target
false positive; candidate v2.1.0 подавляет его. `pr-16` — positive control:
неконтролируемый file-flow в DMZ продолжает получать `PRIN-002`.

## Покрытие правил

| Rule ID | Detect/operator | Positive cases | Representative negative cases | Execution mode |
|---|---|---|---|---|
| PRIN-001 | `field_required` | pr-17 | pr-02, pr-06, pr-19, pr-20 | deterministic |
| PRIN-002 | `field` + `banned` | pr-16 | pr-04, pr-15, pr-18 | deterministic |
| PRIN-003 | `field` + `banned` | pr-18 | pr-01, pr-04, pr-12, pr-16 | deterministic |
| PRIN-004 | отсутствует | — | — | LLM, offline evaluation отсутствует |
| PRIN-005 | отсутствует | — | — | LLM, offline evaluation отсутствует |
| PRIN-006 | отсутствует | — | — | LLM, offline evaluation отсутствует |
| PRIN-007 | отсутствует | — | — | LLM, offline evaluation отсутствует |
| PRIN-008 | `pdn_external_requires_approval` | pr-13 | pr-04, pr-18, pr-23 | deterministic |
| SEAF-001 | `systems_must_exist` | pr-14 | pr-01, pr-04, pr-12, pr-18, pr-23 | deterministic |
| SEAF-002 | `field_matches_registry` (`owner`) | pr-11 | pr-02, pr-06, pr-19, pr-20 | deterministic |
| SEAF-003 | `field_matches_registry` (`criticality`) | pr-19 | pr-02, pr-06, pr-11, pr-20 | deterministic |
| SEAF-004 | `no_endpoint_with_target_status` | pr-12 | pr-01, pr-04, pr-13, pr-18, pr-23 | deterministic |
| SEAF-005 | `required_fields` | pr-20 | pr-02, pr-06, pr-11, pr-17, pr-19 | deterministic |
| SEAF-006 | `flow_present_on_diagram` | pr-10 | pr-01 | deterministic |
| DIAG-001 | `parseable` | pr-21 | pr-01, pr-08, pr-22, pr-23, pr-24 | deterministic |
| DIAG-002 | `node_label_pattern` | pr-08 | pr-01, pr-22, pr-23, pr-24 | deterministic |
| DIAG-003 | `c4_level_declared` | pr-08 | pr-01, pr-22, pr-23, pr-24 | deterministic |
| DIAG-004 | `edges_labeled` | pr-22 | pr-01, pr-08, pr-23, pr-24 | deterministic |
| DIAG-005 | `edges_covered_by_flows` | pr-23 | pr-01, pr-10 | deterministic |
| DIAG-006 | `no_orphan_nodes` | pr-24 | pr-01, pr-08, pr-22, pr-23 | deterministic |
| ADR-001 | `required_sections` | pr-09 | pr-03, pr-07, pr-25, pr-26 | deterministic |
| ADR-002 | `field_in_vocab` | pr-09 | pr-03, pr-07, pr-25, pr-26 | deterministic |
| ADR-003 | `systems_field_must_exist` | pr-25 | pr-03, pr-07, pr-09, pr-26 | deterministic |
| ADR-004 | `required_fields` | pr-26 | pr-03, pr-07, pr-09, pr-25 | deterministic |

## Покрытие deterministic operators

Оператор считается positive-covered только при наличии
несуппрессированного expected finding. Exception-case учитывается как
negative coverage самого правила.

| Detect/operator | Rules | Positive cases | Representative negative cases |
|---|---|---|---|
| `field_required` | PRIN-001 | pr-17 | pr-02, pr-06, pr-19 |
| `field` + `banned` | PRIN-002, PRIN-003 | pr-16, pr-18 | pr-01, pr-04, pr-15 |
| `pdn_external_requires_approval` | PRIN-008 | pr-13 | pr-04, pr-18 |
| `systems_must_exist` | SEAF-001 | pr-14 | pr-01, pr-04, pr-18 |
| `field_matches_registry` | SEAF-002, SEAF-003 | pr-11, pr-19 | pr-02, pr-06, pr-20 |
| `no_endpoint_with_target_status` | SEAF-004 | pr-12 | pr-01, pr-04, pr-18 |
| `required_fields` | SEAF-005, ADR-004 | pr-20, pr-26 | pr-02, pr-03, pr-17, pr-25 |
| `flow_present_on_diagram` | SEAF-006 | pr-10 | pr-01 |
| `parseable` | DIAG-001 | pr-21 | pr-01, pr-22, pr-23 |
| `node_label_pattern` | DIAG-002 | pr-08 | pr-01, pr-22, pr-23 |
| `c4_level_declared` | DIAG-003 | pr-08 | pr-01, pr-22, pr-23 |
| `edges_labeled` | DIAG-004 | pr-22 | pr-01, pr-23, pr-24 |
| `edges_covered_by_flows` | DIAG-005 | pr-23 | pr-01, pr-10 |
| `no_orphan_nodes` | DIAG-006 | pr-24 | pr-01, pr-22, pr-23 |
| `required_sections` | ADR-001 | pr-09 | pr-03, pr-25, pr-26 |
| `field_in_vocab` | ADR-002 | pr-09 | pr-03, pr-25, pr-26 |
| `systems_field_must_exist` | ADR-003 | pr-25 | pr-03, pr-09, pr-26 |

## Denominators

- materialized cases: **26/26**, skipped: **0**;
- deterministic rules: **20**, positive-covered **20/20**, negative-covered **20/20**;
- уникальные deterministic operator shapes: **17**, positive-covered **17/17**,
  negative-covered **17/17**;
- LLM rules: **4**, `llm_cases_evaluated = 0`; LLM coverage не заявляется
  и не смешивается с deterministic denominator.

## Оставшееся ограничение measured scope

Все deterministic-правила и операторы имеют оба полюса coverage.
Непокрытыми остаются четыре LLM-правила; для них нужен отдельный
воспроизводимый fixture/fake-adapter evaluation.
