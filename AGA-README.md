# AGA Project Results workspace

> Исторический pre-SEAF handoff. Не использовать как landing page или финальный
> статус; актуальная точка входа — [`README.md`](README.md), актуальные материалы —
> [`docs/submission/PROJECT-RESULTS.md`](docs/submission/PROJECT-RESULTS.md).

Историческая инструкция, по которой планировалась интеграция с SEAF:
[docs/AGA-SEAF-PROJECT-RESULTS-IMPLEMENTATION-PROMPT.md](docs/AGA-SEAF-PROJECT-RESULTS-IMPLEMENTATION-PROMPT.md).

Рабочий MVP находится в [`aga-skill/`](aga-skill/). Полная инструкция запуска,
архитектура, метрики и честная граница реализованного описаны в
[`aga-skill/README.md`](aga-skill/README.md).

Быстрая проверка:

```bash
cd aga-skill
python3 -m pip install -r requirements-dev.txt
make test
make demo
```

Exact pins зафиксированы, но clean-venv install в этой среде не проверен:
сеть запрещена, полного local wheel cache нет. `make test` и `make demo`
подтверждены в текущем подготовленном окружении.

Фактический результат: 26 materialized offline cases и 20 expected findings.
Baseline: precision 0.9524, outcome/exact accuracy 0.9615, weighted cost 2.0.
Candidate: precision, recall, blocker recall, outcome и exact accuracy 1.0,
weighted cost 0.0. Все 20/20 deterministic rules и 17/17 operators имеют
positive и scope-relevant negative coverage. LLM denominator равен 0 и не смешивается с
deterministic метриками.

Материалы Project Results:

- [`docs/PROJECT-RESULTS.md`](aga-skill/docs/PROJECT-RESULTS.md) — отчёт MVP;
- [`docs/RESULTS-EXAMPLES.md`](aga-skill/docs/RESULTS-EXAMPLES.md) — входы,
  ожидаемые/фактические outputs и метрики;
- [`docs/DEMO-SCRIPT.md`](aga-skill/docs/DEMO-SCRIPT.md) — сценарий видео <3 мин;
- [`docs/AGA-external-enforcement-checklist.md`](aga-skill/docs/AGA-external-enforcement-checklist.md)
  — Git/CI/Ouroboros/ГигаАгент действия.

Официальные веса: отчёт MVP 20%, применение ГигаАгента 10%, демо-видео 30%,
документация и код 10%, результаты на примерах 20%, качество материалов
10%. Реальное подключение ГигаАгента, публичный репозиторий и озвученное видео
ещё требуют внешних действий и не заявляются как выполненные.
