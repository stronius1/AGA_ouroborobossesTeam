# Промпт для модели-исполнителя: SEAF-интеграция и готовность AGA к Project Results

## Как использовать этот документ

Передай модели-исполнителю:

1. всю рабочую папку проекта;
2. этот файл целиком;
3. файл «Критерии оценки Project Results.pdf»;
4. исходный Project Proposal, если он существует;
5. официальную документацию и разрешённый способ доступа к ГигаАгенту.

Модель должна не писать ещё один обзор, а изменить код, тесты, документацию и
локальную конфигурацию. Внешние действия — публикация репозитория, работа с
боевыми credentials, запись голосового видео и отправка заявки — выполняются
только после явного разрешения владельца. Их нельзя отмечать выполненными без
проверяемой ссылки или trace.

Старый файл docs/AGA-remediation-implementation-prompt.md является
историческим: основная часть описанных там дефектов уже исправлена. Не используй
его как актуальный backlog и не возвращай проект к старой шкале оценки.

---

## Роль

Ты — ведущий инженер интеграций, Python/TypeScript-разработчик, архитектор
agentic-систем и release owner хакатонной подачи.

Твоя цель — превратить два пока не связанных дерева, aga-skill и
seaf-archtool-core, в один воспроизводимый продукт:

- SEAF.ArchTool является средой Architecture-as-Code, визуализации и работы с
  архитектурными данными;
- AGA выполняет безопасное governance-ревью изменений и управляемую эволюцию
  правил;
- ГигаАгент выполняет ключевое семантическое ревью и оркестрирует AGA tools;
- итоговая подача закрывает ровно шесть критериев из Project Results PDF.

Не решай задачу косметической правкой README. Нужны SEAF-native input на
синтетических данных, исполняемая интеграция, тестовая корзина ГигаАгента и
проверяемый E2E.

---

## Проверенное текущее состояние

Считай перечисленное ниже отправной точкой, но перепроверь командами до
изменений.

1. Корень workspace не является Git-репозиторием: .git и .gitmodules
   отсутствуют.
2. aga-skill — рабочий offline-first deterministic MVP:
   - 26 materialized golden cases;
   - 20 ожидаемых findings;
   - baseline precision 0.9524, recall 1.0, weighted cost 2.0;
   - candidate precision/recall 1.0, weighted cost 0.0;
   - pytest сообщал 182 passed и 10 subtests passed на момент аудита.
3. Реальный ГигаАгент не подключён:
   - llm_coverage.cases_evaluated равно 0;
   - текущий demo полностью выполняется без агента;
   - local/fake LLM и A2A adapters не являются доказательством критерия.
4. seaf-archtool-core уже находится в workspace, но сейчас это обычная копия,
   которую AGA не импортирует и не вызывает.
5. Аудит показал, что локальное дерево seaf-archtool-core без .git совпадает с
   официальным tag v2026.29.0:
   - upstream: https://gitverse.ru/seafteam/seaf-archtool-core.git
   - commit: 83c82ab1673f1245b499c26b82d507fa602a11d6
6. seaf-archtool-core — инструмент и runtime, а не вся предметная
   SEAF-метамодель. Официальный framework находится в отдельном seaf-core.
   Проверенная начальная pin-версия:
   - upstream: https://gitverse.ru/seafteam/seaf-core.git
   - tag: v1.4.0
   - commit: 60ce335832d2734814c020306a85d1e8b12cf67b
7. AGA сейчас читает synthetic fixtures/seaf.yaml и искусственный формат:

~~~text
meta.yaml
files/systems/*.md
files/flows/*.md
files/adrs/*.md
files/diagrams/*.{puml,mmd}
~~~

   SEAF-native YAML manifests, components и seaf.app.integrations.from/to
   напрямую не поддерживаются.
8. В SEAF.ArchTool уже есть полезные точки интеграции:
   - GigaChat agent;
   - MCP client;
   - SSE и Streamable HTTP transports;
   - function/tool calling;
   - загрузка архитектурного root manifest через
     VUE_APP_DOCHUB_ROOT_MANIFEST.
9. Project Proposal, презентация, публичный URL репозитория, озвученное видео и
   публичный URL видео в workspace отсутствуют.
10. В PDF шестой критерий называется «Качество материалов». Ошибка, при которой
    он назывался «Стабильность», исправлена в актуальных AGA-документах; не
    возвращай старое название при дальнейшей синхронизации.

Не переписывай эти факты в статус «готово» до появления новых доказательств.

---

## Источники истины

При конфликте требований используй такой порядок:

1. Инварианты безопасности: read-only review, fail-closed, HITL для
   blocker/major, no auto-merge, защита corpus и provenance.
2. «Критерии оценки Project Results.pdf» — названия, веса и обязательные
   материалы.
3. Исходный Project Proposal — только после того, как он добавлен в workspace.
4. Реальные контракты pinned версий seaf-archtool-core, seaf-core и официального
   ГигаАгента.
5. Исполняемый код и тесты.
6. Актуальные README/SKILL/EVOLVER.

Нельзя придумывать API ГигаАгента, поля SEAF или ссылки на разделы метамодели.
Если официального контракта нет, реализуй изолированный adapter interface и
честно оставь внешний шаг незакрытым.

---

## Зачем SEAF должен стать основой

Подключение SEAF нужно не ради дополнительной папки в репозитории.

Оно должно дать продукту:

1. SEAF-native Architecture-as-Code формат вместо отдельного несовместимого
   fixture-формата AGA. Сами архитектурные данные при этом могут и должны
   оставаться синтетическими.
2. Один источник архитектурных данных для портала, штатных validators, AGA и
   ГигаАгента.
3. Воспроизводимые ссылки на schema/rule/file/commit вместо выдуманных
   source_ref вида «SEAF-МЕТАМОДЕЛЬ v2.1 §...».
4. Git-based diff синтетического архитектурного репозитория, который можно
   безопасно показать end-to-end.
5. Понятный пользовательский интерфейс для демонстрации проблемы, изменения и
   результата ревью.
6. Нативную точку вызова AGA через уже имеющийся в ArchTool MCP client.
7. Более сильный ответ жюри: AGA не имитирует Architecture-as-Code, а
   встраивается в существующий SEAF-контур.

При этом не утверждай, что один seaf-archtool-core содержит всю SEAF-модель.
Целевое решение состоит минимум из трёх слоёв:

~~~text
SEAF.ArchTool runtime
        +
versioned SEAF framework/metamodel
        +
отдельный репозиторий архитектурных объектов
~~~

---

## Политика данных для хакатона

Синтетические данные разрешены критериями Project Results и являются
рекомендуемым вариантом для этой подачи. Production PR, банковские данные и
доступ к внутреннему архитектурному реестру не требуются.

Требования предъявляются не к происхождению данных, а к качеству эксперимента:

- данные описаны в валидном SEAF-native формате;
- сценарии репрезентативны заявленной проблеме;
- изменения оформлены настоящими base/head Git commits;
- human ground truth зафиксирован до итогового запуска;
- есть positive, negative, clean и near-miss cases;
- входы, фактические выходы и методика оценки опубликованы;
- синтетические результаты не называются production-метриками.

Слово «реальный» далее относится только к фактически исполненному software
flow, MCP-вызову или вызову официального ГигаАгента, но не означает требование
использовать реальные банковские данные.

---

## Целевая архитектура

Реализуй следующий поток:

~~~text
architecture Git repo
  root manifest + SEAF objects + pinned metamodel
                 |
          trusted base/head diff
                 v
     RepositorySnapshotBuilder
                 |
       SEAF -> AGA canonical adapter
                 |
       deterministic AGA guardrails
                 |
       prepare_review MCP result
                 v
   ГигаАгент в SEAF.ArchTool
   semantic rules + tool orchestration
                 |
       finalize_review MCP call
                 v
 schema validation + dedup + verdict
                 |
       comment/report + mandatory HITL

SEAF.ArchTool параллельно отображает тот же root manifest и штатные validators.
~~~

Граница ответственности:

- SEAF.ArchTool не должен содержать forked AGA business logic.
- AGA не должен превращаться в копию SEAF parser/UI.
- Детерминированные проверки остаются кодом.
- PRIN-004, PRIN-005, PRIN-006 и PRIN-007 являются естественным ключевым
  semantic scope ГигаАгента.
- Неполный или ошибочный agent stage не может завершиться approve.
- Merge и применение evolution candidate остаются только за человеком.

---

# Этап 0. Зафиксировать baseline

До первой правки:

1. Прочитай полностью:
   - Критерии оценки Project Results.pdf;
   - AGA-README.md;
   - aga-skill/README.md;
   - aga-skill/SKILL.md;
   - aga-skill/evolver/EVOLVER.md;
   - aga-skill/docs/CURRENT-STATE-AND-ROADMAP.md;
   - aga-skill/docs/PROJECT-RESULTS.md;
   - seaf-archtool-core/README.md;
   - seaf-archtool-core/package.json;
   - релевантный MCP/GigaChat код SEAF.
2. Зафиксируй версии Python, Node, npm, Docker и Compose.
3. Запусти без ослабления тестов:

~~~bash
cd aga-skill
python3 -m pytest -q -p no:cacheprovider
python3 -m unittest discover -s tests
~~~

4. Проверь текущие metrics JSON, llm denominator и demo exit-коды.
5. Зафиксируй inventory мусорных/generated файлов, но не удаляй пользовательские
   файлы до классификации.
6. Сохрани baseline log в локальном рабочем отчёте, не добавляя секреты.

Если baseline расходится с документацией, сначала объясни расхождение. Не
«исправляй» его изменением expected ground truth.

---

# Этап 1. Сделать SEAF воспроизводимой зависимостью

## 1.1. Создать канонический Git-root

Весь продукт должен находиться в одном верхнеуровневом Git-репозитории.

Если .git всё ещё отсутствует:

- локальный git init допустим как подготовительный шаг;
- remote, push и публичность требуют явного разрешения владельца;
- нельзя придумывать URL публичного репозитория.

Создай нормальный root README.md, .gitignore, .gitmodules, Makefile и CI config.
AGA-README.md можно оставить как исторический/расширенный документ, но root
README.md должен быть главным entry point.

## 1.2. Безопасно заменить vendor-copy ArchTool на submodule

Рекомендуемый способ — Git submodule, pinned на конкретный commit без branch
tracking.

Перед заменой:

1. Клонируй upstream во временный каталог.
2. Выполни tree comparison локального snapshot с tag v2026.29.0, исключая
   только .git.
3. Если есть отличия, не теряй их:
   - сохрани patch;
   - классифицируй каждое отличие;
   - проектные overrides вынеси из upstream-каталога.
4. Текущую папку перемещай только в безопасный backup вне Git-root.
5. Добавь submodule по прежнему пути seaf-archtool-core.
6. Checkout строго commit
   83c82ab1673f1245b499c26b82d507fa602a11d6.
7. Не добавляй branch в .gitmodules и не используй плавающий latest.

После этого команда должна быть воспроизводима:

~~~bash
git submodule update --init --recursive
git -C seaf-archtool-core rev-parse HEAD
~~~

## 1.3. Подключить предметную SEAF-метамодель

Добавь отдельный pinned submodule:

~~~text
architecture/vendor/seaf-core
~~~

Начальная audited версия:

~~~text
tag: v1.4.0
commit: 60ce335832d2734814c020306a85d1e8b12cf67b
~~~

Не подменяй seaf-core каталогом public/metamodel/dochub из ArchTool: это разные
назначения.

Если для owner, criticality, target_status или иных корпоративных полей нужен
seaf-dzo-core либо собственное расширение, сначала зафиксируй ADR выбора и
version pin. Не добавляй поля в данные, если их нет в выбранной schema.

## 1.4. Supply chain и лицензии

Обязательно:

- сохранить upstream LICENSE и NOTICE;
- добавить THIRD_PARTY.md или расширить THIRD_PARTY_NOTICES;
- зафиксировать URL, tag, commit, дату аудита и процедуру обновления;
- описать rollback версии;
- проверить license compatibility;
- не коммитить node_modules, dist, credentials и локальные workspace caches.

Subtree допустим только если доказано, что среда оценки не умеет recursive
submodules. В таком случае используй squash import, сохрани commit provenance,
LICENSE/NOTICE и update script. Обычная анонимная копия не допускается.

## Acceptance criteria этапа 1

- fresh clone с --recurse-submodules получает оба upstream дерева;
- git submodule status показывает ожидаемые commits;
- повторный bootstrap не меняет working tree;
- project-owned файлы не изменяют содержимое submodules;
- лицензии и update policy документированы;
- CI явно инициализирует recursive submodules.

---

# Этап 2. Создать исполняемый синтетический архитектурный workspace

Создай каталог architecture как отдельный, но находящийся в submission
репозитории пример Architecture-as-Code.

Минимальная структура:

~~~text
architecture/
  dochub.yaml
  model/
    components.yaml
    integrations.yaml
    adrs.yaml
    contexts.yaml
  docs/
  metamodel/
    aga-extension.yaml        # только если обосновано ADR
  vendor/
    seaf-core/                # pinned submodule
~~~

Требования:

1. Root manifest импортирует pinned локальную SEAF-метамодель и проектные
   объекты.
2. Данные не содержат банковских секретов, ПДн или закрытых идентификаторов.
3. Demo architecture должна содержать как минимум:
   - чистое изменение;
   - зависимость на выводимую систему;
   - новый integration flow;
   - ADR;
   - диаграмму;
   - случай для semantic reuse/ADR review.
4. SEAF.ArchTool должен открывать именно этот manifest, а не собственную
   встроенную документацию.
5. Добавь root compose override вне submodule:
   - read-only mount architecture в public/workspace;
   - VUE_APP_DOCHUB_ROOT_MANIFEST на architecture/dochub.yaml;
   - фиксированный image/build source;
   - healthcheck;
   - secrets только из ignored env.
6. Добавь .env.example только с безопасными именами переменных и placeholders.
7. Добавь smoke test, подтверждающий загрузку root manifest и основных entities.

Не делай architecture каталог ещё одним набором старых AGA fixtures. Это должен
быть валидный синтетический SEAF/DocHub workspace, который фактически
отображается ArchTool.

## Acceptance criteria этапа 2

- npm ci и upstream tests/build проходят на документированной Node 20;
- Docker/Compose healthcheck проходит;
- UI открывается и показывает проектные components/integrations;
- штатные SEAF validators видят demo architecture;
- restart не требует ручного копирования файлов;
- clean shutdown не оставляет изменённые submodules.

---

# Этап 3. Реализовать SEAF -> AGA adapter и исполняемый Git input

## 3.1. Версионированная каноническая модель

Введи явный внутренний контракт, например aga.canonical/v2:

~~~text
System
Integration
ADR
Diagram
ChangedArtifact
RepositoryRevision
SourceProvenance
~~~

Для каждого поля задокументируй:

- источник в SEAF YAML;
- обязательность;
- преобразование;
- поведение при отсутствии;
- schema/version, в которой поле определено;
- реальный source_ref.

Минимальные mappings:

- SEAF components -> AGA System;
- seaf.app.integrations.from/to -> AGA source/target;
- SEAF ADR entity -> AGA ADR;
- context/diagram artifacts -> AGA Diagram;
- Git file path, line/pointer и commit -> provenance.

## 3.2. Безопасный import resolver

SEAF/DocHub root manifests имеют import graph. Resolver должен:

- работать от разрешённого repository root;
- запрещать absolute path, parent traversal, symlink escape и hardlink escape;
- обнаруживать import cycles;
- ограничивать размер, глубину, число файлов и YAML nodes;
- отклонять duplicate IDs и конфликтующие definitions;
- выдавать structured input_error;
- fail closed при неизвестной schema/version;
- не загружать remote imports неявно.

Remote import допускается только как заранее pinned/checksummed dependency.

## 3.3. Trusted RepositorySnapshotBuilder

Текущий GitChangedFilesProvider возвращает только имена файлов и не формирует
исполняемый review snapshot. Исправь контракт:

1. Вход: immutable repository path, base revision, head revision.
2. Changed paths получает Git, а не untrusted meta.yaml.
3. Builder материализует changed artifacts и необходимый import/context closure
   во временный isolated staging.
4. Все файлы проходят safety validation до парсинга.
5. В review log записываются:
   - base/head SHA;
   - architecture manifest hash;
   - ArchTool commit;
   - seaf-core commit;
   - AGA version и rules hash.
6. Повторный review тех же revisions должен быть детерминированным.

Fixture manifest provider оставь только для unit/golden tests.

## 3.4. Перевести submission E2E со старого fixture на SEAF-native snapshot

- fixtures/seaf.yaml остаётся полезным быстрым unit/golden fixture.
- Основной submission E2E читает canonical snapshot синтетического
  architecture repository в SEAF-native формате.
- source_ref ссылается на pinned official schema/rule file либо на явно
  versioned проектное расширение; выдуманные разделы не допускаются.
- Метрики разделяются по dataset, режиму и версии, а не по признаку
  «synthetic/real».

## Обязательные тесты этапа 3

Добавь минимум:

~~~text
test_seaf_native_component_maps_to_system
test_seaf_native_integration_from_to_maps_to_flow
test_unknown_seaf_schema_fails_closed
test_missing_required_extension_field_fails_closed
test_duplicate_entity_id_rejected
test_import_cycle_rejected
test_import_traversal_rejected
test_remote_import_requires_pin_and_checksum
test_git_snapshot_uses_base_and_head
test_manifest_cannot_omit_changed_file
test_context_closure_is_materialized
test_submission_lookup_uses_seaf_native_snapshot
test_review_provenance_contains_all_commits
test_repeat_review_is_deterministic
~~~

Golden tests должны включать clean, broken reference, changed integration,
missing schema, invalid import и negative control.

## Acceptance criteria этапа 3

Фактический Git diff между двумя commits синтетического architecture проходит:

~~~text
base/head -> safe snapshot -> SEAF adapter -> AGA finding -> source evidence
~~~

Finding содержит artifact, location, base/head и проверяемый нормативный
source_ref. Ошибка schema/import не может выглядеть как approve.

---

# Этап 4. Подключить AGA к SEAF.ArchTool через MCP

## 4.1. Реальный MCP server

Добавь к AGA отдельный transport layer, не смешивая его с rule engine.

Требования:

- Streamable HTTP endpoint с non-root path, например /mcp;
- GET и POST согласно контракту pinned ArchTool MCP client;
- tools/list и tools/call;
- strict input/output JSON schemas;
- request size, timeout, concurrency и response size limits;
- structured errors;
- configurable authentication для не-loopback режима;
- no arbitrary filesystem path от клиента;
- безопасное завершение и health endpoint;
- unit, contract и integration tests.

Минимальные tools:

~~~text
aga_prepare_review
aga_seaf_lookup
aga_parse_diagram
aga_finalize_review
~~~

aga_prepare_review возвращает validated deterministic findings и semantic tasks.
aga_finalize_review принимает только schema-validated semantic findings,
проверяет разрешённые rule IDs/source refs, выполняет dedup/precedence и
вычисляет итоговый verdict.

Существующий aga_review_pr можно сохранить как offline composite tool, но demo с
ГигаАгентом должно показывать prepare -> semantic review -> finalize.

## 4.2. Настроить ArchTool scenario

В architecture manifest создай проектный ai-chat scenario на поддерживаемом
pinned ArchTool agent type и подключи AGA через mcp_servers.

Не изменяй upstream SEAF source для project-specific prompt/config, если это
можно описать в architecture manifest или compose override.

Проверь:

- ArchTool получает список AGA tools;
- agent действительно вызывает нужный tool;
- tool result отображается пользователю;
- timeout/error виден как incomplete, а не как пустой успех;
- credentials и raw sensitive payload не попадают в browser/log/video.

## Acceptance criteria этапа 4

- MCP tools/list из ArchTool возвращает AGA tools;
- AGA tool вызывается из agent loop на demo SEAF change;
- normalized result совпадает с прямым AGA result;
- invalid args, timeout и недоступный AGA service fail closed;
- trace содержит tool name, sanitized args hash, status и duration;
- submodules остаются read-only.

---

# Этап 5. Сделать ГигаАгент ключевой частью MVP

Наличие классов GigaChatAgent/MCPClient в исходниках SEAF не доказывает
«Применение ГигаАгента».

Сначала установи по официальным материалам хакатона:

1. Что именно организатор называет ГигаАгентом.
2. Какой runtime/API/SDK обязателен.
3. Как подтверждается реальный запуск.
4. Какие model/version/config разрешены.

Если встроенный agent SEAF не является требуемым ГигаАгентом, реализуй
официальный adapter поверх существующего A2A/LLM boundary. Не переименовывай
GigaChat в ГигаАгент ради критерия.

## Ключевой функционал агента

Передай ГигаАгенту именно семантическую часть, которую нецелесообразно
реализовывать простыми полевыми проверками:

- PRIN-004: reuse before build;
- PRIN-005: единый master данных;
- PRIN-006: смысловая критическая зависимость;
- PRIN-007: необходимость ADR и качество обоснования;
- оркестрацию retrieval/tool calls по связанным SEAF entities.

Детерминированные security/consistency checks остаются guardrails.

В submission E2E выбранный режим semantic review является обязательным:

- без реального ГигаАгента результат имеет status incomplete/error;
- он не должен выдавать тот же полный успешный результат;
- offline deterministic mode остаётся режимом разработки и диагностики, а не
  доказательством агентного критерия.

Ответ агента:

- только JSON по строгой schema;
- только разрешённые rule IDs;
- evidence должно ссылаться на переданные artifacts;
- source_ref берётся из trusted rule catalog;
- raw prose не меняет verdict;
- prompt injection из архитектурного файла не может изменить system policy;
- low-confidence policy и mandatory HITL сохраняются.

## Реальное доказательство

Для разрешённого E2E сохрани sanitized evidence:

~~~text
docs/evidence/gigaagent/run-sanitized.json
docs/evidence/gigaagent/README.md
~~~

Evidence должен содержать:

- дату;
- runtime/model/version;
- hash prompt/config;
- base/head revisions;
- вызванные tools;
- normalized findings;
- latency/token usage, если доступны;
- финальный status/verdict;
- redaction note.

Не коммить credentials, bearer tokens, cookies, полные закрытые prompts или
необезличенные данные.

## Acceptance criteria этапа 5

- есть хотя бы один разрешённый реальный GigaAgent E2E;
- agent выполняет PRIN-004..007 и вызывает AGA tool;
- его finding реально влияет на finalize/verdict;
- отключение агента даёт incomplete;
- fake/fixture и real runs помечены раздельно;
- evidence можно показать жюри без секрета.

---

# Этап 6. Создать независимую test basket ГигаАгента

Текущие 26 deterministic cases сохрани как regression corpus. Не выдавай их за
оценку ГигаАгента.

Создай отдельно:

~~~text
evaluation/gigaagent/corpus.yaml
evaluation/gigaagent/cases/
evaluation/gigaagent/results.json
docs/evidence/evaluation/RESULTS.md
~~~

Требования:

1. Не менее 15 заранее материализованных синтетических SEAF changes.
2. Баланс:
   - positive/negative для PRIN-004..007;
   - clean cases;
   - blocker/major/minor или observation;
   - misleading near-miss;
   - prompt-injection artifact;
   - missing context/incomplete case.
3. Human ground truth фиксируется до финального run.
4. Holdout не используется для подбора prompt/rules.
5. Для каждого case сохраняются:
   - вход;
   - base/head;
   - expected;
   - raw sanitized response;
   - normalized output;
   - PASS/FAIL и причина.
6. Отдельно считай:
   - precision;
   - recall;
   - blocker recall;
   - outcome accuracy;
   - exact case accuracy;
   - schema-valid rate;
   - invalid/hallucinated evidence rate;
   - unsafe approve count;
   - latency.
7. Не смешивай LLM и deterministic denominator.
8. Версия model/prompt/config и corpus hash входят в results.

Минимальный release gate зафиксируй до финального прогона:

~~~text
blocker recall = 1.0
unsafe approve = 0
schema-valid rate = 1.0
precision >= 0.80
recall >= 0.80
outcome accuracy >= 0.85
~~~

Если порог не пройден, не меняй expected после просмотра ответа. Исправляй
prompt, retrieval или adapter на development set, затем один раз запускай
замороженный holdout и честно публикуй результат.

---

# Этап 7. Привести Project Results к шести критериям PDF

Официальная формула:

~~~text
0.20*C1 + 0.10*C2 + 0.30*C3 + 0.10*C4 + 0.20*C5 + 0.10*C6
~~~

Максимум по каждому C — 5. При равенстве итоговых баллов выше место получает
более ранняя отправка.

## C1. Отчёт о результатах фазы MVP — 20%

Подготовь:

- короткую финальную презентацию;
- описание проблемы и пользователя;
- функции MVP;
- архитектуру SEAF + ГигаАгент + AGA;
- необходимые технические детали;
- фактические ограничения;
- дальнейшие шаги;
- трассировку Project Proposal.

Добавь:

~~~text
docs/submission/PROJECT-PROPOSAL.*
docs/submission/PROPOSAL-TRACEABILITY.md
docs/submission/PROJECT-RESULTS.md
docs/submission/presentation-source.*
docs/submission/presentation.pdf
~~~

Для каждой функции Proposal нужна строка:

~~~text
обещание -> статус -> код/тест/evidence -> timestamp в видео
~~~

Если Proposal не предоставлен, не выдумывай его. Подготовь шаблон и отметь
единственный внешний blocker.

## C2. Применение ГигаАгента — 10%

В отчёте покажи:

- почему semantic review без агента непрактичен;
- какой ключевой scope он выполняет;
- реальный E2E trace;
- отдельные agent metrics;
- поведение при недоступности;
- safety boundary.

Нельзя ссылаться только на наличие dependency, класса, mock или нулевой
llm_coverage.

## C3. ДЕМО-видео — 30%

Перепиши текущий DEMO-SCRIPT после заморозки интерфейса и метрик.

Финальный ролик обязан:

- быть строго короче 180 секунд;
- иметь непрерывную понятную голосовую озвучку;
- показать полный E2E;
- объяснить проблему в первые 20 секунд;
- показать изменение в SEAF.ArchTool;
- показать реальный запуск ГигаАгента;
- показать вызов AGA tool;
- показать semantic + deterministic findings;
- показать итог и HITL/no auto-merge;
- назвать test basket и честные метрики.

Рекомендуемая история:

~~~text
проблема -> SEAF change -> ГигаАгент -> AGA tool ->
finding/evidence -> HITL -> измеренный результат
~~~

После записи:

- проверить длительность через ffprobe;
- проверить голос, читаемость и отсутствие секретов;
- открыть ссылку в приватном окне без авторизации;
- добавить URL в Project Results.

Сценарий без реального ГигаАгента не является финальным.

## C4. Документация и код — 10%

Обязательны:

- публичный репозиторий;
- root README.md;
- назначение и архитектура;
- git clone --recurse-submodules;
- one-command bootstrap;
- offline demo и real E2E instructions;
- troubleshooting;
- лицензии;
- CI clean-clone proof.

Проверь публичный URL без авторизации. Не пиши placeholder как реальную ссылку.

## C5. Результаты на примерах — 20%

Публикуй два честно разделённых блока:

1. Existing deterministic regression corpus: 26 cases.
2. Frozen GigaAgent synthetic SEAF basket: фактически полученные результаты.

Для каждого case должен быть виден вход, human expected, фактический выход и
PASS/FAIL. Приложи machine-readable raw/normalized evidence и методику.

## C6. Качество материалов — 10%

Проверь, что во всех актуальных документах сохранено точное название
«Качество материалов», а историческое «Стабильность» не вернулось.

Собери единый лаконичный narrative:

~~~text
проблема -> решение -> почему SEAF -> роль ГигаАгента ->
E2E -> результаты -> ограничения -> roadmap
~~~

Требования:

- один визуальный стиль;
- единые термины и цифры;
- нет незаполненных placeholders в отчёте, слайдах и видео
  (явные примеры в .env.example допустимы);
- нет битых ссылок;
- нет взаимоисключающих claims;
- landing page короткий, подробности вынесены в evidence;
- финальная вычитка другим человеком/моделью.

---

# Этап 8. Репозиторий, CI и submission hygiene

## Root commands

Сделай понятные цели, например:

~~~bash
make bootstrap
make test
make test-seaf
make demo-offline
make demo-e2e
make project-results-check
~~~

demo-e2e с реальным агентом не должен автоматически запускаться в публичном CI
без secrets. В CI нужны mock/contract tests; разрешённый real run выполняется
отдельно и сохраняет sanitized evidence.

## CI

Публичный CI должен:

- checkout recursive submodules;
- проверять pins;
- ставить exact Python dependencies;
- использовать документированную Node 20;
- запускать Python tests;
- запускать SEAF adapter/MCP contract tests;
- запускать npm tests/build;
- валидировать manifests;
- проверять ссылки и отсутствие placeholders;
- сканировать случайно добавленные secrets;
- не менять repository tree.

## Cleanup

Убери из актуальной подачи:

- .DS_Store;
- __pycache__;
- *.pyc;
- .pytest_cache;
- временные build outputs;
- повторные runtime logs;
- секреты и локальные env;
- stale generated files.

Ценные зафиксированные результаты перенеси из временного build в versioned
docs/evidence/snapshots с manifest/hash. Исторические review/remediation
документы не удаляй без причины, но перенеси в docs/archive или явно пометь
historical, чтобы они не противоречили актуальному состоянию.

---

# Полная проверка результата

Выполни проверку из нового временного каталога, а не из подготовленного
workspace:

~~~bash
git clone --recurse-submodules PUBLIC_URL clean-clone
cd clean-clone
make bootstrap
make test
make test-seaf
make demo-offline
make project-results-check
~~~

В разрешённом окружении с официальными credentials:

~~~bash
make demo-e2e
~~~

Дополнительно проверь:

~~~bash
git submodule status --recursive
git status --short
~~~

Ожидания:

- все команды имеют документированные exit-коды;
- tree после test/demo чистый;
- submodules стоят на pinned commits;
- offline fixture evidence и evidence реального вызова агента не смешаны;
- public links открываются без авторизации;
- video duration меньше 180 секунд;
- real GigaAgent evidence ненулевой;
- HITL/no auto-merge сохраняются.

---

# Definition of Done

Работа завершена только если одновременно:

1. seaf-archtool-core подключён с проверяемым provenance и pin.
2. Предметная SEAF-метамодель тоже подключена и versioned.
3. ArchTool отображает проектный architecture manifest.
4. AGA анализирует SEAF-native synthetic YAML и фактический base/head Git diff.
5. Submission E2E использует синтетический SEAF-native repository, а старый
   flat fixture остаётся unit/golden инструментом.
6. AGA доступен ArchTool через настоящий MCP server.
7. Официальный ГигаАгент выполняет ключевое semantic review.
8. Ошибка/отсутствие агента даёт incomplete, не approve.
9. Есть frozen independent agent basket и ненулевые metrics.
10. Есть clean-clone CI proof.
11. Есть root README и публичная ссылка на код.
12. Есть финальные Project Results и Proposal traceability.
13. Есть озвученное demo video строго короче 180 секунд и публичная ссылка.
14. Во всех актуальных материалах критерий 6 называется «Качество материалов».
15. В submission-материалах нет незаполненных placeholders, секретов, битых
    ссылок и противоречивых цифр.

Локальную инженерную часть можно считать завершённой раньше только с явным
списком внешних действий. Project Results readiness нельзя объявлять полной,
пока отсутствуют public repo, real GigaAgent trace или озвученное видео.

---

# Запреты

- Не вносить project-specific изменения прямо в pinned upstream submodules.
- Не использовать latest или непинованные branches/images.
- Не называть vendor-copy интеграцией.
- Не считать seaf-archtool-core предметной SEAF-метамоделью.
- Не выдумывать owner/criticality/target_status без schema.
- Не доверять changed_files из untrusted manifest.
- Не отправлять секреты и закрытые архитектурные данные модели.
- Не позволять raw LLM prose менять verdict.
- Не ослаблять golden expected или gate ради красивой метрики.
- Не смешивать deterministic и agent metrics.
- Не выполнять commit, push, publish, merge или внешние сообщения без
  разрешения владельца.
- Не заявлять public URL, video URL или real integration без проверки.
- Не выполнять auto-merge и не применять evolution candidate автоматически.

---

# Формат финального отчёта модели-исполнителя

Верни владельцу:

## 1. Итог

Что реально стало работать end-to-end, 5–10 строк.

## 2. Изменённые артефакты

Таблица:

~~~text
path | назначение | ключевое изменение
~~~

## 3. Проверки

Для каждой команды:

~~~text
command | exit code | ключевой результат | evidence path
~~~

## 4. Матрица Project Results

Для всех C1–C6:

~~~text
критерий | вес | статус | доказательство | оставшийся шаг
~~~

Используй только статусы:

~~~text
done
partial
external action required
blocked
~~~

## 5. Метрики

Раздельно:

- deterministic regression;
- GigaAgent development set;
- GigaAgent frozen holdout.

## 6. Внешние действия владельца

Только конкретные действия, которые модель не могла выполнить: credentials,
public remote, запись голоса, публикация URL, отправка заявки.

## 7. Ограничения и риски

Честно укажи незакрытые риски и не называй проект готовым, если Definition of
Done не выполнен.
