# AGA Project Results

> **Исторический pre-SEAF snapshot.** Документ сохранён как evidence
> предыдущей локальной стадии и не описывает текущую submission-готовность.
> Актуальный отчёт: [`../../docs/submission/PROJECT-RESULTS.md`](../../docs/submission/PROJECT-RESULTS.md),
> agent basket: [`../../docs/evidence/evaluation/RESULTS.md`](../../docs/evidence/evaluation/RESULTS.md).

Срез доказательств: **15 июля 2026 года**. Этот документ следует шести
критериям из «Критерии оценки Project Results.pdf» с точными весами
**20% / 10% / 30% / 10% / 20% / 10%**. Он отделяет работающий локальный MVP
от внешних интеграций и материалов, которые ещё не готовы.

Кратко: AGA — offline-first пакет для ревью Architecture-as-Code изменений и
управляемой эволюции правил по подтверждённым прецедентам. Текущий
воспроизводимый контур является детерминированным локальным MVP. Он не
публикует ветки или PR, не выполняет merge и пока не подключён к реальному
ГигаАгенту/Ouroboros.

## 1. Отчёт о результатах фазы MVP — 20%

**Статус: частично закрыто.** Работающий MVP и технические доказательства
есть; исходный Project Proposal в рабочей папке не найден, поэтому полное
подтверждение всех заявленных в нём функций требует отдельной сверки.

### Реализовано

- Вход ревью — зафиксированный PR snapshot: `meta.yaml` и архитектурные
  артефакты в `files/`.
- Движок валидирует вход fail-closed, применяет rules-as-code к паспортам АС,
  интеграционным потокам, ADR, PlantUML и Mermaid и формирует findings с
  `rule_id`, severity и `source_ref`.
- Blocker/major приводят к эскалации человеку; ошибки входа и неполный анализ
  не могут превратиться в `approve`.
- Evolver читает подтверждённый прецедент, проверяет защищённый corpus
  snapshot, создаёт изолированный candidate правил, сравнивает метрики и
  пропускает его только через проверяемый gate.
- Результат эволюции остаётся набором build-артефактов. Publisher по умолчанию
  работает в `dry_run`; локальная команда только независимо переигрывает
  mutation/fitness/gate. Применение candidate и merge требуют отдельной
  внешней reviewed VCS-процедуры.
- Есть локальные контракты feedback loop, A2A, LLM fixture и publisher.

### Доказательства

- Движок ревью: [`tools/aga.py`](../tools/aga.py).
- CLI ревью: [`scripts/run_review.py`](../scripts/run_review.py).
- Candidate-only evolver: [`scripts/run_evolution.py`](../scripts/run_evolution.py).
- Политика fitness-гейта: [`evolver/fitness.py`](../evolver/fitness.py).
- Защищённый набор из 26 materialized cases:
  [`golden/corpus.yaml`](../golden/corpus.yaml).
- Последний локальный запуск `make demo` 15 июля 2026 года: exit `0`,
  `real 1.54 s`; были показаны blocker-review, evolution, дельта метрик и
  проверка build-артефактов.
- Последний локальный запуск `make test`: **182 passed, 10 subtests passed**.
- Проверяемый candidate manifest:
  [`candidate-manifest.json`](../../docs/evidence/snapshots/deterministic-2026-07-15/candidate-manifest.json).

Матрица реализованного scope ниже отражает только факты репозитория, а не
заменяет отсутствующий исходный Project Proposal.

| Возможность | Фактический статус | Доказательство |
|---|---|---|
| Ревью Architecture-as-Code snapshot | Реализовано локально | `make review`, `tools/aga.py` |
| Fail-closed валидация входа | Реализовано локально | validation tests и structured errors |
| Эволюция правила по прецеденту | Реализована как изолированный candidate | `make demo`, [`rules.diff`](../../docs/evidence/snapshots/deterministic-2026-07-15/rules.diff) |
| Fitness и защита от деградации | Реализовано на 26-case golden corpus | `metrics-*.json`, gate checks |
| Автоматическое применение/merge | Намеренно не реализовано | `auto_merge: false`; локальная команда только независимо валидирует bundle, применение — external action required |
| Реальный draft PR | Не подключён; только dry-run | `publisher-result.json` |
| Реальный ГигаАгент/Ouroboros | Не подключён | external action required |

### Ограничения

- Исходный Project Proposal или ссылка на него отсутствуют в workspace.
- Golden corpus и SEAF registry — синтетические fixtures, а не банковский
  production-контур.
- Candidate v2.1.0 зафиксирован в
  [`candidate-rules`](../../docs/evidence/snapshots/deterministic-2026-07-15/candidate-rules/principles.yaml),
  но не применён к
  production rules и не слит человеком.
- Внешние Ouroboros, Git provider, CI и ГигаАгент не настроены.

### Следующие шаги

1. Добавить исходный Project Proposal и выполнить построчную трассировку
   `заявленная функция → статус → доказательство → timestamp в видео`.
2. Провести независимую проверку MVP на реальном репозитории Architecture-as-Code.
3. После человеческого review применить либо отклонить candidate отдельной
   атомарной human-only VCS-транзакцией; локальный валидатор source tree не
   меняет.
4. Подключить внешние интеграции, перечисленные в следующих разделах.

## 2. Применение ГигаАгента в MVP — 10%

**Статус: не закрыто. Реальное применение ГигаАгента не заявляется.**

### Реализовано

- Определён безопасный синхронный `LLMAdapter` с разделением trusted
  instruction и untrusted artifact content, строгой JSON-схемой findings,
  catalog/artifact/location binding, fail-closed confidence policy и выключенной
  по умолчанию сетью. После timeout не остаётся background worker.
- Реализован детерминированный `FixtureLLMAdapter` для offline tests.
  Его выход явно помечается synthetic/non-release.
- Определён A2A protocol `schedule_task / wait_for_task / get_task_result` и
  локальный backend; failure/timeout дают явный `incomplete_error`.
- В `tools/aga.py` сохранена узкая точка адаптации к внешнему оркестратору без
  выдумывания неподтверждённой сигнатуры реального API.

### Доказательства

- [`tools/llm.py`](../tools/llm.py)
- [`tools/a2a.py`](../tools/a2a.py)
- [`tools/aga.py`](../tools/aga.py)
- В обоих свежих metrics-артефактах честно указано:
  `llm_coverage.cases_evaluated = 0`,
  `status = not_measured_offline`.

### Ограничения

- В репозитории нет настроенного адаптера, identity или credentials реального
  ГигаАгента.
- Демо выполняет детерминированный локальный контур; ГигаАгент не берёт на
  себя его ключевой функционал.
- Качество LLM/ГигаАгент-ответов на тестовой корзине не измерялось.
- Поэтому требование «без ГигаАгента решение невозможно или нецелесообразно»
  текущими доказательствами не подтверждено.

### Следующие шаги

1. Согласовать официальный API/SDK и модель исполнения ГигаАгента.
2. Реализовать отдельный network adapter с явным opt-in, timeout, лимитом
   ответа и типизированными ошибками.
3. Передать ГигаАгенту ключевую семантическую часть ревью четырёх LLM rules,
   сохранив детерминированные security checks и HITL.
4. Добавить offline fixtures и отдельные LLM-метрики, затем прогнать
   разрешённый интеграционный тест без публикации секретов.
5. Показать реальный вызов и полезный результат в финальном видео.

## 3. ДЕМО-видео — 30%

**Статус: технический E2E готов; обязательное озвученное видео отсутствует.**

### Реализовано

- Одна команда `make demo` запускает полный локальный сценарий:
  blocker-review `pr-12` → подтверждение ожидаемой эскалации → обработка
  pending-прецедента → изолированная мутация → baseline/candidate fitness →
  gate → build-артефакты → dry-run publisher.
- Ожидаемый exit `1` blocker-review не скрывается, но корректно принимается
  demo-оркестрацией; общий demo завершается с exit `0` только после проверки
  артефактов.
- Подготовлен сценарий ролика продолжительностью 2:30–2:50.

### Доказательства

- [`Makefile`](../Makefile)
- [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md)
- [`evolution-pr.md`](../../docs/evidence/snapshots/deterministic-2026-07-15/evolution-pr.md)
- [`rules.diff`](../../docs/evidence/snapshots/deterministic-2026-07-15/rules.diff)
- [`metrics-baseline.json`](../../docs/evidence/snapshots/deterministic-2026-07-15/metrics-baseline.json)
- [`metrics-candidate.json`](../../docs/evidence/snapshots/deterministic-2026-07-15/metrics-candidate.json)

### Ограничения

- **Ссылка на озвученное демо-видео: не создана — external action required.**
  Сейчас видео, голосовая озвучка и проверенная длительность
  `< 180 секунд` отсутствуют.
- Локальный E2E не демонстрирует реальную интеграцию ГигаАгента.

### Следующие шаги

1. Записать экран и голос по [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md).
2. Удержать итоговую длительность в диапазоне 2:30–2:50 и строго `< 3 минут`.
3. Проверить звук, читаемость терминала и отсутствие секретов.
4. Опубликовать видео, проверить доступ без авторизации и добавить реальный URL выше.

## 4. Документация и код — 10%

**Статус: локальный код и документация есть; публичный репозиторий не
подтверждён.**

### Реализовано

- Пакет содержит README, процедуры SKILL/EVOLVER, rules-as-code, fixtures,
  tests, шаблоны и воспроизводимые demo-команды.
- Runtime и dev зависимости закреплены в `requirements*.txt` и
  `pyproject.toml`; заявлена совместимость с Python 3.10+.
- Добавлены три документа Project Results, ориентированные на новую шкалу.

### Доказательства

- [`pyproject.toml`](../pyproject.toml)
- [`requirements.txt`](../requirements.txt)
- [`requirements-dev.txt`](../requirements-dev.txt)
- [`README.md`](../README.md) — существующая инструкция, требующая
  финальной синхронизации.
- Команда `make test` на текущем snapshot: **182 passed, 10 subtests passed**.

### Ограничения

- **Ссылка на публичный репозиторий: не создана — external action required.**
  В переданной рабочей папке нет `.git`, поэтому remote,
  публичность и запуск из чистого clone не проверены.
- Установка в пустой venv не проверена: сеть запрещена, полного
  локального wheel cache нет; подтверждены только exact pins и работа
  в текущем подготовленном окружении.
- Числа README синхронизированы с этим 26-case snapshot, но
  публичный clean-clone запуск ещё не подтверждён.
- Реальная настройка CI, protected branch и CODEOWNERS не подтверждена.

### Следующие шаги

1. Опубликовать код в публичном репозитории и добавить реальный URL.
2. Выполнить установку и `make demo && make test` из чистого clone.
3. Проверить публичную доступность без авторизации.

## 5. Результаты на примерах — 20%

**Статус: закрыто для детерминированного локального MVP; не закрыто для
ГигаАгент/LLM-части.**

### Реализовано

- Материализованы и фактически обработаны 26 golden cases: чистые изменения,
  minor warnings, major/blocker findings, контролируемое исключение и
  отрицательный контроль для слишком широкого исключения.
- Baseline обнаруживает 20/20 ожидаемых findings, но добавляет один false
  major на `pr-15`.
- Изолированный candidate устраняет этот false positive и сохраняет finding
  на `pr-16`.

### Доказательства

Полная таблица `вход → ожидание → факт → статус` и методика находятся в
[`RESULTS-EXAMPLES.md`](RESULTS-EXAMPLES.md).

| Метрика | Baseline | Candidate |
|---|---:|---:|
| cases evaluated | 26 | 26 |
| precision | 0.9524 | 1.0 |
| recall | 1.0 | 1.0 |
| blocker recall | 1.0 | 1.0 |
| outcome accuracy | 0.9615 | 1.0 |
| exact case accuracy | 0.9615 | 1.0 |
| weighted cost | 2.0 | 0.0 |
| FP / FN | 1 / 0 | 0 / 0 |

Оба запуска используют один corpus revision, один canonical hash всех
materialized fixture bytes и один набор весов ошибок; это зафиксировано в
metrics-артефактах.

### Ограничения

- Результат candidate — оценка изолированных правил в `build`, а не уже
  принятой production-версии.
- 26 cases являются небольшим синтетическим golden corpus; результат 1.0 не
  доказывает качество на произвольных реальных PR.
- Все 20/20 deterministic rules и 17/17 operator shapes имеют positive и
  scope-relevant negative coverage; корпус по-прежнему не исчерпывающий.
- LLM/GigaAgent denominator равен нулю и не смешивается с deterministic
  метриками.

### Следующие шаги

1. Создать независимый holdout и прогнать реальные обезличенные PR.
2. Добавить отдельную тестовую корзину для ГигаАгента/LLM rules.
3. После human approval применить bundle одной проверяемой VCS-транзакцией и
   повторить метрики на принятой версии правил.

## 6. Качество материалов — 10%

**Статус: структура материалов подготовлена; финальное визуальное оформление
ещё требуется.** Критерий PDF требует ёмкости, логики повествования и
дизайн-оформления всех представляемых материалов.

### Реализовано

- Материалы организованы в последовательности: проблема → MVP → E2E →
  результаты → ограничения → следующие шаги.
- Demo проверяет наличие и непустоту ключевых артефактов и отсутствие
  незаполненных template placeholders.
- Candidate manifest содержит хэши, `gate_passed`,
  `human_confirmation_required: true` и `auto_merge: false`.
- Полный локальный test suite проходит воспроизводимо.

### Доказательства

- [`candidate-manifest.json`](../../docs/evidence/snapshots/deterministic-2026-07-15/candidate-manifest.json)
- [`publisher-result.json`](../../docs/evidence/snapshots/deterministic-2026-07-15/publisher-result.json)
- [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md)
- [`RESULTS-EXAMPLES.md`](RESULTS-EXAMPLES.md)
- Проверки 15 июля 2026 года: `make demo` exit `0`; `make test` —
  182 passed и 10 subtests passed.

### Ограничения

- Финальные слайды, запись видео и единый визуальный стиль ещё не подготовлены.
- README синхронизирован с 26-case metrics; остаётся финальная
  редакторская вычитка всего пакета.
- Публичные ссылки ещё не созданы и не проверены.

### Следующие шаги

1. Синхронизировать README и презентацию с этим evidence snapshot.
2. Подготовить короткие слайды в едином стиле и выполнить редакторскую вычитку.
3. Проверить все ссылки и материалы в режиме без авторизации.
4. Перед отправкой выполнить финальный чек:
   `make demo && make test`, длительность видео `< 180 секунд`, внешние ссылки
   созданы и проверены.
