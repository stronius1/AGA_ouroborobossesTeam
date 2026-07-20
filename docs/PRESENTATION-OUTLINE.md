# Презентация Project Results: 8 слайдов

Каждый слайд ниже содержит один вывод. Цифры берутся только из
[`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json); перед экспортом deck нужно
сверить командой `make submission-consistency-check`.

## 1. Ручной architecture governance — bottleneck

**Вывод:** регулярная ручная сверка Architecture-as-Code с SEAF, ADR и
принципами отнимает время и даёт неодинаковое качество.

- Визуал: AS IS flow `PR → очередь → ручная сверка → итерации`.
- Цифра: 25 ч/нед на блок — proposal-сценарий, не production measurement.
- Не показывать `4.1 млн ₽` без пометки «гипотеза».

## 2. AGA превращает review в проверяемый advisory pipeline

**Вывод:** AGA выдаёт severity, точное evidence и source reference, а спорное
эскалирует человеку.

- Визуал: `Git diff → AGA → approve advisory / escalate`.
- Подчеркнуть: `human_review_required=true`, `auto_merge=false`.

## 3. Ouroboros замыкает архитектурный self-evolution loop

**Вывод:** роль агента — не чат и не обёртка: три отдельные задачи выполняют
review, remediation и re-review через trusted AGA MCP boundary.

- Показать три реальные task ID из retained evidence.
- Зафиксированная стоимость этого controlled run: `0.113183 USD`.
- Не называть его broad quality release.

## 4. Trusted architecture: модель не получает власть над repository

**Вывод:** schema, revisions, evidence и применение patch контролирует trusted
host; модель не может сама push/approve/merge.

- Визуал: boundary `Ouroboros ↔ AGA MCP ↔ trusted Git snapshot`.
- Отдельно: только `synthetic-public` во внешнем model path.

## 5. Полный Demo E2E сходится в один safety gate

**Вывод:** две параллельные ветки — архитектура и правила — должны пройти пять
проверок вместе.

- Generated scenario: 11 nodes, 9 flows.
- Architecture: `SEAF-004 → patch → 0 findings`.
- Rules: 26 baseline + 26 candidate checks.
- Gate: workspace, finding closed, candidate tests, no regression, strict
  improvement.

## 6. Улучшение измеримо, measurement boundaries не смешаны

**Вывод:** candidate исправил только `pr-15`, сохранил negative control
`pr-16` и поднял deterministic exact result с 25/26 до 26/26.

- Precision: `0.9524 → 1.0`; recall и blocker recall остаются `1.0`.
- Рядом честно показать historical semantic frozen `10/16`, unsafe approve
  `2`, release gate `FAIL`.
- Fixture `16/16` подписать `non-release`.

## 7. Safety/HITL — часть продукта, а не оговорка

**Вывод:** любой missing context, invalid schema/evidence или blocker/major
останавливает автономный проход.

- Candidate-only changes.
- No raw secrets/prompts/provider payloads in evidence.
- MVP remediation ограничен `SEAF-004` и explicit `replaced_by`.
- Нового trusted all-case semantic PASS пока нет.

## 8. Ценность подтверждаем пилотом, не маркетинговой цифрой

**Вывод:** proposal-сценарий даёт 5.35 ч/нед на архитектора, ≈4.1 млн ₽ gross и
≈15× gross/model-call cost только при явных допущениях; следующий шаг — shadow
pilot и полный TCO.

- Base assumptions: 30 PR, 50 мин, 65%×3 мин, 35%×15 мин, 48 недель,
  4 000 ₽/ч, 2 USD/PR, 95 ₽/USD.
- Roadmap: human review 48-case development-v2 → пять повторов → новый
  holdout → public clean clone → internal runtime, RBAC/audit → production
  pilot.
- Финальная строка: «advisory MVP работает; release quality и ROI ещё должны
  быть доказаны».

## Ссылки для speaker notes

- [Project Results](PROJECT-RESULTS.md)
- [Proposal traceability](PROPOSAL-TRACEABILITY.md)
- [Business-effect calculation](BUSINESS-EFFECT.md)
- [Demo video script](DEMO-VIDEO-SCRIPT.md)
- [Submission checklist](SUBMISSION-CHECKLIST.md)
