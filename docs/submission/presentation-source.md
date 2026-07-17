---
title: "AGA + SEAF"
subtitle: "Evidence-backed governance for Architecture-as-Code"
lang: ru
---

# Архитектурный риск прячется в корректном YAML

- Архитектор вручную связывает компоненты, потоки, ADR и lifecycle.
- Дубли master-data и зависимости на выводимые системы требуют семантики.
- Ошибка ревью дороже дополнительной эскалации.

**Пользователь:** enterprise / solution architect, ревьюящий Architecture-as-Code change.

# Один SEAF-native источник

Синтетический workspace содержит components, `seaf.app.integrations`, ADR и
contexts/PlantUML. Project manifest настроен как единый root для ArchTool и AGA;
UI-проверка ожидает подключения pinned upstream trees.

```text
pinned ArchTool + pinned seaf-core + project architecture
```

Никаких production-данных, ПДн или закрытых идентификаторов.

# Целевой поток MVP

```text
Git base/head -> safe import closure -> aga.canonical/v2
 -> deterministic guardrails -> MCP prepare
 -> agent semantic review -> MCP finalize -> HITL
```

Git → SEAF → MCP prepare/finalize и official-agent stage проверены через
Ouroboros `v6.64.1` и OpenRouter. Канонический blocker smoke прошёл; frozen
16-case run технически завершился, но semantic release gate получил `FAIL`.

Каждый finding сохраняет commit, file, JSON Pointer, hash и реальный
versioned source reference.

# Почему ключевой scope — у агента

- PRIN-004: найти смысловой дубль и кандидата reuse.
- PRIN-005: отличить второй master от read-only replica.
- PRIN-006: распознать критическую зависимость в prose/ADR.
- PRIN-007: оценить необходимость и достаточность обоснования ADR.

Field/schema/security checks остаются детерминированными.

# Fail closed и человеческий контроль

- Нет успешных prepare + finalize одного review → `incomplete`.
- Только strict JSON, allowlisted rule/source/artifact/evidence.
- Prompt injection остаётся untrusted architecture data.
- Blocker/major → обязательный HITL.
- Auto-merge и автоматическое применение evolution отсутствуют.

# Измеренный deterministic baseline

| Corpus | Cases | Precision | Recall | Blocker recall | Weighted cost |
|---|---:|---:|---:|---:|---:|
| Baseline | 26 | 0.9524 | 1.0 | 1.0 | 2.0 |
| Isolated candidate | 26 | 1.0 | 1.0 | 1.0 | 0.0 |

Agent denominator не смешивается с этими числами.

# Frozen GigaAgent basket

- 16 synthetic SEAF base/head cases: 8 development + 8 holdout.
- Positive/negative PRIN-004..007, clean, blocker, near-miss.
- Prompt injection, missing context и multi-finding.
- Fixture scorer: 16/16 PASS, P/R/blocker/outcome/schema = 1.0,
  unsafe approve = 0; `release_evidence: false`.
- Gate до запуска: blocker recall 1.0; unsafe approve 0; schema-valid 1.0;
  precision/recall ≥ 0.80; outcome accuracy ≥ 0.85.
- Frozen real: development 6/8, holdout 4/8; overall P/R/blocker =
  0.50/0.50/0.50, outcome = 0.8125, schema = 1.0, unsafe approve = 2.

**Real measurement denominator: 16; release gate: FAIL. Повтора holdout нет.**

# Честный статус и следующие шаги

Локально: 600 tests + 32 subtests (99 unittest), offline Git→SEAF→finding, MCP
contracts и реальный Ouroboros loop. Следующий semantic цикл требует generic
redesign без tuning на раскрытом holdout и новую untouched holdout. Внешне ещё
нужны public repo, озвученное видео <180 s и исходный Project Proposal.
Action/image/package digests и clean-clone CI — также release-owner checks.

**Narrative:** один SEAF source → agent semantic reasoning → deterministic
safety → evidence → человек принимает решение.
