# Поддерживаемые мутации AGA Evolver

Каждая мутация содержит непустой `provenance` вида `precedent:<id>` или
`incident:<id>` и проходит `evolver.mutations.validate_mutation()` до создания
candidate. Runtime поддерживает ровно пять типов:

| Тип | Назначение | Ключевые ограничения | Semver |
|---|---|---|---|
| `add_exception` | Узкое доказанное исключение | `id/rationale/provenance/when`; global/tautology запрещены | minor |
| `adjust_severity` | Изменение severity | downgrade blocker только с approved `committee_decision` | minor |
| `add_rule` | Новое candidate-rule | unique ID, `source_ref`, provenance; active blocker запрещён | minor |
| `activate_rule` | Candidate → active | только явный `human_approval` | minor |
| `deprecate_rule` | Вывод правила | reason, evidence, exact trusted FP/negative coverage; blocker требует committee | minor |

Пример безопасного исключения:

```yaml
type: add_exception
provenance: precedent:0001
rule_id: PRIN-002
exception:
  when:
    all:
      - {field: zone, equals: dmz}
      - {field: pattern, equals: file}
      - {field: transfer_mode, equals: batch}
      - {field: gateway_controlled, equals: true}
      - {field: approvals, contains: security}
  rationale: "Контролируемая batch-выгрузка через DMZ-шлюз"
  provenance: precedent:0001
```

Condition DSL: `equals`, `contains`, `in`, `all`, `any`, dotted fields.

Для `deprecate_rule` поле `coverage` не является самоподписанным
доказательством. `positive_cases` обязан в точности совпасть со
всеми baseline cases, где target-rule дал false positive;
`negative_cases` — со всеми scope-relevant baseline cases без fire и
expected finding этого правила. Оба множества выводятся из locked
baseline `per_pr`/deterministic coverage и сверяются exact. Gate также
требует, чтобы ground truth не ожидал target-rule, candidate его не
emit-ил, а per-case findings всех остальных правил не изменились.
Обычные no-FN/no-regression и strict-improvement checks не ослабляются.

`add_fewshot`, `edit_template` и `refine_wording` намеренно не заявляются:
для них пока нет безопасного applicator contract. Изменение fitness,
permissions, corpus expected, security-инвариантов или error weights мутацией
не является и отклоняется policy guard до fitness.

Evolver пишет только `build/`. `scripts/apply_candidate.py` — несмотря на
историческое имя — работает только как независимый валидатор: повторно строит
кандидата из текущих rules и pending-прецедента, пересчитывает fitness/gate и
никогда не пишет в source tree. После этой проверки отдельный local-only
connector `scripts/publish_candidate.py` связывает bundle с exact Git HEAD и
создаёт атомарный candidate commit в disposable worktree. В commit входят
только изменённые rules, `VERSION`, полный `CHANGELOG.md`, distilled precedent
и PR-shaped report/sanitized manifest. Connector не умеет push, PR, approve
или merge; исходные HEAD/index/worktree остаются неизменны.
