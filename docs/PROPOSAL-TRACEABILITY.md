# Project Proposal → фактический MVP

Дата сверки: 20 июля 2026 года. Числа синхронизированы с
[`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json). Исходный документ:
[`Project_Proposal_AGA_SberAIHack.pdf`](../Project_Proposal_AGA_SberAIHack.pdf).

| Обещание Proposal | Фактический MVP | Статус и evidence |
|---|---|---|
| Автономный review Architecture-as-Code | Trusted Git base/head snapshot, deterministic SEAF/ADR/diagram guardrails и semantic principles review через Ouroboros | Реализовано; [MCP contract](MCP-CONTRACT.md) |
| PR/webhook или cron trigger | Локальные CLI/UI entrypoints; реальный Bitbucket/GitHub webhook не подключён | Частично; integration roadmap |
| PR MCP + workspace + A2A | AGA MCP gateway, exact worker tool envelopes, SEAF workspace и Ouroboros tasks | Реализовано на synthetic-public data; [runbook](SELF-EVOLUTION-RUNBOOK.md) |
| Severity и ссылка на источник | Findings содержат rule, severity, artifact, location, evidence и source reference; invalid evidence rejected | Реализовано и покрыто contract tests |
| Auto-approve чистых PR | AGA может выдать advisory verdict `approve`, но не выполняет repository approve, push или merge | Изменено ради safety; `human_review_required=true`, `auto_merge=false` |
| Эскалация blocker/major | `request_changes_escalate`; решение остаётся у архитектора | Реализовано; [accepted smoke evidence](evidence/ouroboros/run-sanitized.json) |
| 13 demo PR с ground truth | 26 materialized golden cases для deterministic baseline/candidate fitness; исторический 16-case semantic freeze; новый 48-case development-v2 с human review `pending` | Расширено; [deterministic evidence](evidence/snapshots/deterministic-2026-07-15-v2/README.md), [semantic results](evidence/evaluation/RESULTS.md) и [development-v2](../evaluation/development-v2/README.md) |
| 15 systems в synthetic SEAF fixture | Full UI preset каждый раз генерирует 11-node, 9-flow scenario и SEAF workspace | Изменено; проверяется `make demo-verify` |
| 7 auto-approve · 3 major · 3 blocker · 1 minor | Proposal одновременно называл 13 PR и раскладку из 14 исходов; MVP не наследует этот противоречивый denominator и публикует точный 26-case corpus | Расхождение раскрыто, не нормализовано задним числом |
| Precision/recall на test basket | Пять раздельных measurement boundary: deterministic 26-case, controlled live E2E, development-v2 без model metrics, non-release 16-case fixture и исторический frozen real FAIL | Реализовано с ограничениями; [Project Results](PROJECT-RESULTS.md#7-%D0%BC%D0%B5%D1%82%D1%80%D0%B8%D0%BA%D0%B8-%D0%B8-measurement-boundary) |
| Stretch: ADR/fix suggested patch | Candidate-only remediation поддержанного `SEAF-004`, re-review и отдельная эволюция rules по human precedent | Реализовано в ограниченном scope; произвольный patch/auto-apply не заявляется |
| Публичный GitHub demo repository | Текущий checkout и документация подготовлены, но public remote URL отсутствует | **Внешний submission blocker** |
| Экономия 5.35 ч/нед, ≈4.1 млн ₽, ≈15×, 65% fast path | Сохранён исходный сценарий и добавлены weeks/hourly rate/FX; production baseline не измерен | Только hypothesis; [формула и sensitivity](BUSINESS-EFFECT.md) |
| Без реальных банковских данных | Все внешние model calls ограничены `synthetic-public`; secrets и raw provider payloads не входят в evidence | Реализовано |
| Production-safe internal deployment | Cloud/internal model, RBAC, secret store, audit и реальные endpoints не входят в MVP | Roadmap, не текущая функция |

## Что изменилось концептуально

Proposal описывал один проход `review → approve/escalate`. MVP добавил два
candidate-only контура:

```text
review → remediation → re-review
human precedent → rule mutation → 26-case fitness
                         \       /
                      unified gate → HITL
```

Это усиливает роль Ouroboros в демонстрации: три реальные задачи выполняют
review, remediation и re-review архитектурного изменения. При этом 26-case
fitness остаётся детерминированным, чтобы semantic model не мог «оценить сам
себя» и выдать себе PASS.

## Формулировка готовности для всех материалов

> Реализован advisory synthetic-public MVP полного self-evolution E2E с
> обязательным HITL. Локальный deterministic demo и controlled live
> review/remediation/re-review проходят safety gate; нового broad semantic
> release PASS пока нет, а исторический frozen run завершился FAIL.

Эту формулировку следует использовать в README, отчёте, презентации и видео.
