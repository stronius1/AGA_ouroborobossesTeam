# Сценарий озвученного AGA demo

> Исторический pre-SEAF материал. Не использовать для финальной подачи;
> актуальный сценарий: [`../../docs/submission/DEMO-SCRIPT.md`](../../docs/submission/DEMO-SCRIPT.md).

Целевая длительность: **2:30–2:50**, жёсткий предел из критериев —
**строго меньше 3 минут**. План ниже рассчитан примерно на **2:43**.

Статус материала: сценарий готов, запись ещё не создана.

**Ссылка на озвученное демо-видео: не создана — external action required.**

## Что демонстрируется

Один воспроизводимый локальный E2E:

```text
Architecture-as-Code PR snapshot
  → fail-closed review
  → blocker + HITL escalation
  → подтверждённый precedent
  → изолированный candidate rules
  → fitness baseline/candidate
  → gate
  → build artifacts
  → dry-run publisher, без merge
```

Реальный ГигаАгент в текущем snapshot не подключён. В ролике нельзя говорить,
что он выполняет ревью. Можно показать только подготовленные LLM/A2A
контракты и явно назвать интеграцию следующим шагом.

## Подготовка до записи

Выполнить вне ролика из корня репозитория:

```bash
cd aga-skill
python3 -m pip install -r requirements-dev.txt
make test
make demo
```

Ожидаемое на проверенном snapshot:

- `make test`: 182 passed, 10 subtests passed;
- `make demo`: exit `0`;
- review внутри demo возвращает ожидаемый exit `1` из-за blocker, после чего
  demo продолжает evolution;
- baseline: 26 cases, precision 0.9524, recall 1.0, weighted cost 2.0;
- candidate: 26 cases, precision 1.0, recall 1.0, weighted cost 0.0;
- publisher: `dry_run`, `external_side_effects: false`.

Перед записью:

- открыть терминал в каталоге `aga-skill`;
- увеличить шрифт так, чтобы строки читались без паузы;
- скрыть уведомления, домашний путь и любые секреты;
- очистить терминал;
- не показывать и не озвучивать публичные URL, пока placeholders не заменены.

## Поминутный план и текст озвучки

### 0:00–0:16 — проблема

**На экране:** заголовок `AGA — Architecture Governance Agent` и короткая
схема из раздела выше.

**Озвучка:**

> Архитектурный репозиторий содержит паспорта систем, потоки, ADR и диаграммы.
> Ручное ревью таких изменений медленное, а пропуск зависимости на выводимую
> систему или несогласованной передачи персональных данных дорог. AGA
> превращает правила governance в воспроизводимую проверку PR.

### 0:16–0:36 — решение и границы MVP

**На экране:** быстро показать каталоги `rules/`, `golden/`, `evolver/`,
`tools/`.

Команда для компактного кадра:

```bash
find rules golden evolver tools -maxdepth 1 -type f -o -type d | sort
```

**Озвучка:**

> MVP принимает локальный snapshot PR, валидирует вход fail-closed, применяет
> rules-as-code и возвращает findings с severity и нормативным основанием.
> Отдельный evolver может предложить изменение правила по подтверждённому
> прецеденту, но не имеет права применить его или выполнить merge.

### 0:36–1:06 — запуск полного E2E и blocker-review

**На экране:** выполнить единственную основную команду:

```bash
make demo
```

Остановить прокрутку на блоке `pr-12`, `SEAF-004`, `blocker` и
`Request changes + эскалация архитектору`.

**Озвучка:**

> Запускаю полный сценарий. В `pr-12` новый MQ-поток ведёт в систему со
> статусом eliminate. Правило SEAF-004 выдаёт blocker со ссылкой на источник.
> Exit 1 здесь ожидаем: blocker обязан остановить автоматический approve и
> перейти к человеку. Make проверяет этот контракт и только затем продолжает
> безопасный evolution cycle.

### 1:06–1:36 — эволюция по прецеденту

**На экране:** продолжение вывода `make demo`: шаги `[1/6]`–`[6/6]`.
Показать `precedent:0001`, `add_exception → PRIN-002`, `GATE PASS`.

**Озвучка:**

> Evolver берёт подтверждённый архитектором прецедент о контролируемом batch
> обмене в DMZ. Он проверяет защищённый corpus snapshot, создаёт копию правил
> и добавляет узкое исключение: DMZ, file, batch, контролируемый шлюз и
> согласование security должны выполняться одновременно. Исходные правила не
> изменяются.

### 1:36–2:06 — результат на 26 примерах

**На экране:** вывести только сводные метрики:

```bash
jq '{cases_evaluated,precision,recall,blocker_recall,outcome_accuracy,exact_case_accuracy,weighted_cost,fp_total,fn_total,llm_coverage}' build/metrics-baseline.json
jq '{cases_evaluated,precision,recall,blocker_recall,outcome_accuracy,exact_case_accuracy,weighted_cost,fp_total,fn_total,llm_coverage}' build/metrics-candidate.json
```

**Озвучка:**

> На двадцати шести materialized cases baseline находит все двадцать ожидаемых
> нарушений, но даёт один false major: precision 0,9524 и точность вердиктов
> 0,9615. Candidate убирает ошибку на контролируемом `pr-15`, сохраняя major
> на неконтролируемом `pr-16`. Precision, recall и blocker recall становятся
> единицами, weighted cost снижается с двух до нуля.

Мелким, но читаемым титром вывести: `deterministic corpus only; LLM cases = 0`.

### 2:06–2:28 — safety gate и отсутствие автопубликации

**На экране:**

```bash
jq '{gate_passed,human_confirmation_required,auto_merge}' build/candidate-manifest.json
jq '{publisher,status,external_side_effects,branch_name,draft_pr_url}' build/publisher-result.json
```

**Озвучка:**

> Gate запрещает падение blocker recall, рост ошибок, смену корпуса и весов
> ошибок. Manifest требует человеческого подтверждения, auto-merge выключен.
> Publisher работает в dry-run: ветка и PR фактически не создаются, внешних
> side effects нет.

### 2:28–2:43 — итог и честное ограничение

**На экране:** финальная карточка:

```text
26 cases · 20/20 expected findings · blocker recall 1.0
candidate only · human merge · GigaAgent: external action required
```

**Озвучка:**

> Итог — воспроизводимый локальный MVP ревью и безопасной эволюции правил.
> Следующий обязательный шаг — подключить реальный ГигаАгент для семантических
> правил и измерить его отдельно. Текущие единичные метрики относятся только
> к небольшому детерминированному golden corpus.

## Команды E2E без монтажных сокращений

Если нужен один непрерывный terminal take, достаточно:

```bash
cd aga-skill
make demo
sed -n '/| Метрика |/,/Гейт:/p' build/evolution-pr.md
jq '{gate_passed,human_confirmation_required,auto_merge}' build/candidate-manifest.json
jq '{status,external_side_effects,branch_name,draft_pr_url}' build/publisher-result.json
```

`jq` используется только для компактного отображения уже созданных JSON и не
является runtime-зависимостью AGA. Если на машине записи его нет, открыть те
же файлы в редакторе и показать указанные поля.

## Финальный чек видео

- [ ] Полное время находится между 2:30 и 2:50 и строго меньше 180 секунд.
- [ ] Есть непрерывная разборчивая голосовая озвучка.
- [ ] В первые 20 секунд понятны проблема и пользовательская ценность.
- [ ] Показан полный путь от входного PR до findings, gate и артефактов.
- [ ] В кадре читаются `SEAF-004`, `blocker`, `26 cases` и дельта метрик.
- [ ] Явно сказано, что candidate не применён и publisher является dry-run.
- [ ] Не заявлено использование реального ГигаАгента до его подключения.
- [ ] В кадре нет токенов, ключей, персональных данных и локального username.
- [ ] Ссылка открывается в приватном окне без авторизации.
- [ ] Реальная публичная ссылка добавлена в Project Results.
