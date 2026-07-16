# AGA: текущее состояние и план работ

**Дата среза:** 15 июля 2026 года  
**Текущая стадия:** локальный SEAF-native MVP; внешние submission-доказательства не готовы.

Главная landing page — [`../../README.md`](../../README.md), актуальный отчёт
по C1–C6 —
[`../../docs/submission/PROJECT-RESULTS.md`](../../docs/submission/PROJECT-RESULTS.md).
Этот документ описывает инженерный handoff внутри пакета AGA.

## Что работает локально

- Legacy regression engine и candidate-only evolver сохранены: 26
  materialized cases, baseline precision `0.9524`, recall `1.0`, blocker recall
  `1.0`; isolated candidate не применён автоматически.
- `RepositorySnapshotBuilder` читает explicit base/head из Git object database,
  сам получает changed paths и материализует bounded import/context closure во
  временный staging.
- `DocHubImportResolver` отклоняет traversal, symlink/hardlink escape, remote
  import без pin/checksum, cycles, duplicate/conflicting IDs и превышение
  resource limits.
- `SeafCanonicalAdapter` переводит SEAF components, integrations, ADR и
  context/diagram artifacts в versioned `aga.canonical/v2` с
  commit/file/JSON Pointer/hash provenance.
- Submission prepare формирует deterministic findings и обязательные semantic
  tasks PRIN-004..007. Без semantic finalize итог остаётся `incomplete`.
- MCP transport предоставляет prepare/lookup/diagram/finalize как отдельную от
  rule engine границу со strict schemas, limits, structured errors, trace и
  health endpoint.
- `make demo-offline` воспроизводимо создаёт синтетические SEAF-native base/head
  commits и обнаруживает новую зависимость на component со статусом
  `target_status: eliminate`. Это диагностический, не agent run.
- Отдельная frozen basket содержит 16 синтетических SEAF changes: 8 development
  и 8 holdout, с locked human expected и release gate до реального запуска.
- Root Compose настроен на read-only project architecture, MCP в internal
  Docker network и project-owned ArchTool `gigachat` scenario; runtime ещё не
  запускался без pinned upstream деревьев.
- Blocker/major всегда требуют HITL; auto-merge, commit, push и publisher side
  effects отсутствуют.

## Честные границы доказательства

| Область | Статус |
|---|---|
| SEAF-native Git → adapter → finding | локально реализовано и покрыто тестами |
| MCP protocol и prepare/finalize | локальный unit/contract scope |
| SEAF.ArchTool UI/build/runtime | ожидает pinned submodules и Node 20 environment |
| SEAF upstream provenance | pins задокументированы; submodules не созданы без разрешения на fetch |
| Официальный ГигаАгент | real adapter/credentials/trace отсутствуют; denominator `0` |
| Agent basket | 16 frozen cases готовы; real results `not_run` |
| Git root | локально инициализирован; remote и public URL отсутствуют |
| Root review revisions | проектный `HEAD`/base commit отсутствует: commit не был разрешён |
| CI | workflow подготовлен; public clean-clone run отсутствует |
| Project Proposal | исходный документ не предоставлен; traceability заблокирована |
| Demo video | есть план `2:50`; запись, `ffprobe` proof и public URL отсутствуют |

## Команды

Из корня проекта:

```bash
make test
make demo-offline
make project-results-check
```

После разрешённого подключения pinned upstream деревьев и установки Node 20:

```bash
make bootstrap
make test-seaf
```

`make demo-e2e` — explicit opt-in. Без проверенного официального agent adapter
он обязан завершиться exit `2` со статусом `incomplete`, а не подменить агент
fixture-ответом.

## Следующие действия

### Локально после разрешения на read-only upstream fetch

1. Сравнить существующий `seaf-archtool-core` с tag `v2026.29.0`, сохранить
   любые отличия и безопасный backup вне Git-root.
2. Подключить ArchTool и `architecture/vendor/seaf-core` как recursive
   submodules на задокументированных commits, без branch tracking.
3. Проверить LICENSE/NOTICE, pins, штатные validators, Node tests/backend build,
   Compose health и отображение project manifest в UI.
4. Повторить все проверки из чистого локального clone.

### Только владелец или отдельное явное разрешение

1. Предоставить официальный Project Proposal и контракт ГигаАгента.
2. Настроить разрешённые credentials и выполнить real E2E без раскрытия
   секретов; сохранить sanitized trace и отдельно прогнать development/holdout.
3. Создать remote/public repository, запустить public CI и проверить clone без
   авторизации.
4. Записать непрерывно озвученное видео строго короче 180 секунд, проверить
   `ffprobe`, приватное окно и public URL.
5. Выполнить submission, push, publish или иные внешние сообщения.

## Evidence и contracts

- [`../../docs/SEAF-CANONICAL-MAPPING.md`](../../docs/SEAF-CANONICAL-MAPPING.md)
  — field-level mapping и fail-closed policy.
- [`../../docs/MCP-CONTRACT.md`](../../docs/MCP-CONTRACT.md) — transport,
  correlation, finalization и deployment boundary.
- [`../../architecture/`](../../architecture/) — synthetic-public SEAF-native
  workspace.
- [`../../evaluation/gigaagent/`](../../evaluation/gigaagent/) — frozen agent
  basket и transport-free scorer.
- [`../../docs/evidence/baseline/2026-07-15.md`](../../docs/evidence/baseline/2026-07-15.md)
  — неизменённый pre-implementation baseline.
- [`docs/RESULTS-EXAMPLES.md`](RESULTS-EXAMPLES.md) — 26-case deterministic
  regression evidence.
- [`AGA-external-enforcement-checklist.md`](AGA-external-enforcement-checklist.md)
  — repository/identity/SoD controls.
