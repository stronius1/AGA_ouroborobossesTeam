# Ручной architecture governance — bottleneck

### AGA + Ouroboros · Sber AI Hack

Цифры синхронизированы с каноническим `SUBMISSION-FACTS.json`.

- Architecture-as-Code PR нужно сверять с SEAF, ADR, диаграммами и принципами.
- Ручной review создаёт очередь и неодинаковое качество комментариев.
- Proposal-сценарий: **25 ч/нед** на блок; это гипотеза, не production-замер.

**Вывод:** рутинную проверку нужно автоматизировать, сохранив решение за архитектором.

# AGA превращает review в проверяемый pipeline

```text
immutable Git base/head
        ↓
trusted snapshot + guardrails
        ↓
semantic review + exact evidence
        ↓
advisory verdict → HITL
```

- Severity, artifact, JSON Pointer, evidence и source reference.
- Missing context или ошибка дают `incomplete`, а не optimistic approve.
- `auto_merge=false`.

# Ouroboros замыкает self-evolution loop

Три реальные controlled задачи:

1. `2c3b23ff` — review: найден blocker `SEAF-004`.
2. `bfd18932` — remediation: минимальный candidate patch.
3. `49c3a905` — re-review: целевой finding закрыт.

- Только AGA MCP tools и `synthetic-public` evidence.
- Retained cost: **0.113183 USD**.
- Это доказательство E2E, не broad quality release.

# Trusted boundary ограничивает автономность

```text
Ouroboros                    Trusted host
   │                             │
   └──── AGA MCP schema ─────────┤
         bounded evidence        ├─ immutable Git revisions
         receipts                ├─ evidence validation
                                 └─ candidate-only patch
```

- Модель не получает произвольный filesystem path или credentials.
- Агент не может push, repository-approve или merge.
- Blocker/major всегда требуют человека.

# Полный Demo E2E: две ветки, один gate

```text
11 nodes / 9 flows → review → remediation → re-review ─┐
                                                       ├→ 5 checks → HITL
precedent → rule candidate → 26× baseline/candidate ──┘
```

- `demo.legacy_scoring → demo.scoring_v2` — одна строка.
- `pr-15` исправлен; negative control `pr-16` сохранён.
- Gate проверяет workspace, closure, outcomes, regressions и strict improvement.

# Результат измерим — границы не смешаны

| Measurement | Результат | Честный вывод |
|---|---:|---|
| Rule fitness | 25/26 → **26/26** | Узкая mutation без регрессии |
| Controlled live E2E | 3 tasks, gate PASS | Ouroboros/MCP loop работает |
| Fixture | 16/16, non-release | Scorer и plumbing работают |
| Historical semantic freeze | **10/16**, unsafe approve 2 | Release gate FAIL |

# Safety/HITL — часть продукта

- Conservative approve: только complete rules + valid evidence + resolved context.
- Prompt/artifact text разделены на trusted instruction и untrusted data.
- Remediation ограничен `SEAF-004` и explicit `replaced_by`.
- Candidate остаётся локальным; `human_review_required=true`.
- Старый раскрытый holdout нельзя повторно использовать для release claim.

**Вывод:** система автономна в анализе, но не в необратимом решении.

# Ценность подтверждаем пилотом

- Proposal-сценарий: **5.35 ч/нед** экономии на архитектора.
- **≈4.1 млн ₽** — gross time-value при 48 неделях и 4 000 ₽/ч.
- **≈15×** — gross/model-call cost, не полный ROI.

Следующие gates:

1. 48-case development-v2 → human review → 5 стабильных прогонов.
2. Freeze → один новый untouched holdout.
3. Public clean clone + видео <3 минут.
4. Shadow pilot: latency, quality, TCO и ручные overrides.

**Advisory MVP работает; release quality и ROI ещё должны быть доказаны.**
