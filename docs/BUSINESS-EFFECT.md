# Бизнес-эффект: формула, допущения и sensitivity

Цифры `5.35 ч/нед`, `≈4.1 млн ₽` и `≈15×` — **сценарий из Project
Proposal, а не измеренный production ROI**. Канонические входы и вычисленные
значения хранятся в [`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json) и
проверяются командой `make submission-consistency-check`.

## Базовый сценарий Proposal

| Параметр | Значение | Статус источника |
|---|---:|---|
| PR в неделю на блок | 30 | Явно в Proposal |
| Ручное review одного PR | 50 мин | Явно в Proposal |
| Быстрый проход | 65% по 3 мин | Явно в Proposal; гипотеза, не auto-merge |
| Эскалация | 35% по 15 мин | Явно в Proposal |
| Архитекторов в блоке | 4 | Явно в Proposal |
| Model calls | 2 USD на PR | Явно в Proposal |
| Рабочих недель в год | 48 | Добавленное допущение |
| Полная стоимость часа архитектора | 4 000 ₽ | Добавленное допущение для воспроизведения ≈4.1 млн ₽ |
| Курс | 95 ₽/USD | Добавленное допущение для воспроизведения ≈15× |

«Быстрый проход» в текущем MVP означает advisory `approve` с возможностью
выборочного человеческого контроля. Он не означает GitHub/Bitbucket approve и
не запускает merge.

## Проверяемая формула

Обозначения:

- `N` — PR в неделю;
- `Mm` — минут ручного review на PR;
- `q` — доля быстрого прохода;
- `Mq`, `Me` — минуты быстрого и escalated прохода;
- `A` — число архитекторов;
- `W` — рабочих недель;
- `C` — стоимость часа архитектора;
- `Cm` — model cost на PR в USD;
- `FX` — ₽/USD.

```text
T_manual = N × Mm / 60
T_agent  = N × (q × Mq + (1 − q) × Me) / 60
T_saved  = T_manual − T_agent

Saved_per_architect = T_saved / A
Annual_gross        = T_saved × W × C
Annual_model_cost   = N × W × Cm × FX
Annual_after_calls  = Annual_gross − Annual_model_cost
Gross_value/calls   = Annual_gross / Annual_model_cost
```

Подстановка базовых значений:

```text
T_manual = 30 × 50 / 60 = 25.0 ч/нед
T_agent  = 30 × (0.65 × 3 + 0.35 × 15) / 60 = 3.6 ч/нед
T_saved  = 21.4 ч/нед на блок = 5.35 ч/нед на архитектора

Annual_gross       = 21.4 × 48 × 4 000 = 4 108 800 ₽
Annual_model_cost  = 30 × 48 × 2 × 95 = 273 600 ₽
Annual_after_calls = 3 835 200 ₽
Gross_value/calls  = 4 108 800 / 273 600 = 15.02×
```

Таким образом, `≈4.1 млн ₽` — gross time-value, а `≈15×` делит её только на
стоимость model calls. Это **не полный ROI**: знаменатель не включает
разработку, инфраструктуру, интеграцию, безопасность, эксплуатацию, аудит и
стоимость ошибочных решений.

## Sensitivity

| Сценарий | PR/нед | Manual, мин | Fast share / fast, мин | Escalated, мин | ₽/ч | Model $/PR | Экономия блока, ч/нед | Gross, ₽/год | Model, ₽/год | Gross/model |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Низкий | 15 | 35 | 50% / 5 | 20 | 3 000 | 3 | 5.625 | 810 000 | 205 200 | 3.95× |
| Базовый | 30 | 50 | 65% / 3 | 15 | 4 000 | 2 | 21.4 | 4 108 800 | 273 600 | 15.02× |
| Высокий | 45 | 60 | 75% / 2 | 10 | 5 000 | 1 | 42.0 | 10 080 000 | 205 200 | 49.12× |

Во всех строках использованы 48 недель, четыре архитектора и 95 ₽/USD. Таблица
показывает, что результат особенно чувствителен к реальному времени ручного
review, доле быстрого прохода и полной стоимости внедрения, которой здесь нет.

## Что уже измерено, а что нужно измерить

Измерено в MVP:

- controlled synthetic-public Ouroboros review/remediation/re-review:
  `0.113183 USD` за три задачи;
- исторический 16-case frozen semantic run: `0.409884 USD` за 85 model calls,
  но release gate `FAIL`;
- 26-case deterministic fitness: 25/26 → 26/26.

Не измерено:

- реальное число архитектурных PR и ручные minutes-touch-time;
- доля PR, для которых advisory approve принимается без дополнительной работы;
- время архитектора на проверку agent evidence и false positives;
- production model/runtime, storage, observability и support cost;
- цена задержки, пропущенного blocker и ошибочной эскалации;
- эффект обучения и изменения процесса после внедрения.

## План подтверждения business case

1. Зафиксировать 4–6 недель AS IS: volume, touch time, queue time и outcome.
2. Выполнить shadow pilot без auto-merge и измерить agent cost/latency/quality.
3. Разделить быстрые, escalated, incomplete и manually-overridden PR.
4. Рассчитать TCO с инфраструктурой и эксплуатацией, затем диапазон ROI.
5. Только после safety gate и аудита рассматривать выборочное расширение
   автономии.

