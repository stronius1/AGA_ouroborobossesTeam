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

Локально проверены Git → SEAF → MCP prepare/finalize boundaries. Official-agent
stage — external / not run; real denominator равен 0.

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

**Текущий real denominator: 0 — официальный запуск ещё не разрешён.**

# Честный статус и следующие шаги

Локально: 381 tests + 32 subtests (98 unittest), offline Git→SEAF→finding, MCP contracts,
regression и frozen basket. Ожидают разрешения: upstream submodules; внешне ещё
нужны официальный GigaAgent trace, public repo, озвученное видео <180 s и
исходный Project Proposal. Action/image/package digests и clean-clone CI —
также release-owner checks, а не локальное доказательство.

**Narrative:** один SEAF source → agent semantic reasoning → deterministic
safety → evidence → человек принимает решение.
