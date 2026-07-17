# AGA + SEAF.ArchTool

AGA — advisory-контур governance-ревью изменений Architecture-as-Code.
Синтетическая SEAF-архитектура служит одним источником для
SEAF.ArchTool, детерминированных AGA guardrails и семантического
agent-этапа. Blocker/major всегда требуют HITL; auto-merge отсутствует.

## Статус

Offline-контур AGA и обвязка для Ouroboros закреплены на stable
`v6.64.1`. Целевой provider — OpenRouter, точная Main/semantic-модель —
`deepseek/deepseek-v4-pro`. Внешней модели можно передавать только
зафиксированные `synthetic-public` fixtures.
Материализатор, read-only preflight, trusted backend и runner реализованы и
проверены как offline, так и через реальный runtime. Канонический blocker smoke
прошёл; единственный frozen run выполнил все 16 случаев, но semantic release
gate завершился `FAIL`: development 6/8, holdout 4/8, overall precision/recall/
blocker recall `0.50/0.50/0.50`, outcome `0.8125`, schema-valid `1.0`, unsafe
approve `2`. Повтор holdout не выполнялся и для этого freeze запрещён.

OpenRouter key хранится только в owner-only настройках изолированного профиля
вне Git; hard cap установлен в `50 USD`. В OpenRouter отправлялись только
`synthetic-public` данные. Санитизированные smoke/development evidence и
non-release отчёт о frozen FAIL находятся в `docs/evidence/ouroboros/`.
Понятный статус и план продолжения:
[`docs/CURRENT-STATUS-AND-NEXT-STEPS.md`](docs/CURRENT-STATUS-AND-NEXT-STEPS.md).

## Слои продукта

```text
SEAF.ArchTool runtime (pinned submodule)
        +
SEAF framework/metamodel (pinned submodule)
        +
architecture/ — synthetic SEAF-native objects
        |
trusted base/head Git diff → safe snapshot → AGA canonical model
        → deterministic guardrails → MCP prepare
        → Ouroboros v6.64.1 semantic PRIN-004..007
        → MCP finalize → HITL
```

- [`architecture/`](architecture/) — синтетический Architecture-as-Code workspace.
- [`aga-skill/`](aga-skill/) — review engine, rules, adapters, MCP и tests.
- `seaf-archtool-core/` — pinned GitVerse submodule
  `83c82ab1673f1245b499c26b82d507fa602a11d6`.
- `architecture/vendor/seaf-core/` — pinned GitVerse submodule
  `60ce335832d2734814c020306a85d1e8b12cf67b`.
  Project-owned logic в upstream trees не вносится.
- [`docs/`](docs/) — текущий handoff, технические контракты и evidence.

## Быстрая локальная проверка

Нужны Python 3.10+ и version-pinned Python packages из
`aga-skill/requirements-dev.txt`.

```bash
make test
make demo-offline
```

`make demo-offline` создаёт изолированные синтетические SEAF-native base/head
commits, получает changed paths из Git и показывает детерминированный blocker
с commit/file/JSON Pointer evidence. Финальный статус намеренно остаётся
`incomplete`, потому что offline-запуск не подменяет real Ouroboros task.

Для ArchTool нужны Node 20 и npm 8.1+. После подключения pinned
submodules clean clone и bootstrap выполняются так:

```bash
git clone --recurse-submodules "$AGA_REPOSITORY_URL" aga-seaf
cd aga-seaf
make bootstrap
make test
make test-seaf
```

`AGA_REPOSITORY_URL` должен содержать проверенный public URL. Сейчас
remote ещё не создан; переменная не задана, и эта команда не
выдаётся за уже проверенный clone.

## Контролируемый Ouroboros smoke

OpenRouter key уже сохранён в owner-only (`0600`) settings изолированного
Ouroboros-профиля вне Git; positive hard cap равен `50 USD`. Ключ не передаётся
CLI, не пишется в `.env`, Git, логи или evidence.

Main route должен точно указывать
`deepseek/deepseek-v4-pro`; Heavy/Light/Vision/Consciousness — быть
пустыми или точно той же моделью; Deep Self Review, Websearch,
Scope Review и все Review/Scope Review Models — точно той же
моделью. Cross-model/local fallback отключён,
`OUROBOROS_TASK_REVIEW_MODE=off`.
Внешний instruction skill `aga_review` version `1.0.0` установлен, прошёл
standard Ouroboros skill review и включён без permissions.

Локально скачанный macOS DMG `v6.64.1` совпал с SHA-256 из
гайда и прошёл `hdiutil verify`, но `codesign --verify` вернул
`invalid signature`, а `spctl` — internal error. Приложение не устанавливалось
и signature bypass не применялся. Вместо него Ouroboros собран в изолированном
окружении из точного чистого upstream commit для `v6.64.1`; preflight проверяет
commit, версию и live overlay attestation. Обычный lifecycle:

```bash
make ouroboros-materialize
make ouroboros-preflight
make demo-e2e
```

`make demo-e2e` уже выполнил blocker smoke `ga-05-critical-eliminate` успешно.
После code freeze команда `evaluate-ouroboros-all` была выполнена ровно один
раз и завершилась semantic `evaluation_gate_failed`. Не запускайте отдельный
holdout или повторный all-run для этого freeze; будущий релизный цикл потребует
новой untouched holdout. Точные pins, настройка MCP и sanitized capture описаны в
[`docs/evidence/ouroboros/README.md`](docs/evidence/ouroboros/README.md).

Project-local materialization предназначена только для offline preview.
Real runner повторно валидирует и материализует fixture под нейтральным
`/private/tmp/aga-synthetic-public/ouroboros-cases`, чтобы provider context не
раскрывал пользовательский absolute workspace path.

## Команды

| Команда | Назначение |
|---|---|
| `make bootstrap` | Инициализировать submodules и dependencies из version/lock manifests |
| `make test` | Все Python unit/regression/contract tests |
| `make test-seaf` | Pins, manifests, SEAF adapter/snapshot и ArchTool tests/build |
| `make demo-offline` | Воспроизводимый synthetic flow без network/credentials |
| `make ouroboros-materialize` | Создать ignored, locked synthetic-public Git fixture для smoke |
| `make ouroboros-preflight` | Без model call проверить v6.64.1, все exact model routes, hard cap, review settings, reviewed/enabled skill и ровно 4 AGA tools |
| `make demo-e2e` | Opt-in trusted Ouroboros smoke на `ga-05-critical-eliminate`; fail closed без configuration |
| `OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-development` | Non-release real 8-case development diagnostic; только в новом цикле |
| `OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-holdout` | Не запускать для текущего freeze: frozen holdout уже раскрыт измерением |
| `OUROBOROS_FULL_RUN_APPROVED=yes make evaluate-ouroboros-all` | Не повторять текущий failed freeze; будущий цикл требует новой untouched holdout и разрешения |
| `make project-results-check` | Core hygiene, pins, contracts и evidence checks |

Machine-readable deterministic evidence is frozen with hashes in
[`docs/evidence/snapshots/deterministic-2026-07-15-v2/`](docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md).

## Troubleshooting

- `dependency_not_initialized`: выполните
  `git submodule update --init --recursive`, затем `make verify-pins`.
- MCP registry принимает только два полных immutable revision SHA;
  не подставляйте branch name или выдуманный commit.
- `node`/`npm` отсутствуют: для upstream ArchTool установите документированный
  Node 20, затем запускайте `make test-seaf` только после submodule bootstrap.
- `docker compose` отвечает, но healthcheck недоступен: убедитесь, что Docker
  daemon запущен и submodules инициализированы.
- `make ouroboros-preflight` или `make demo-e2e` возвращают typed
  `not_configured`: проверьте trusted packaged Ouroboros `v6.64.1`, все
  exact model routes, owner-supplied hard cap, Advisory mode,
  `OUROBOROS_TASK_REVIEW_MODE=off`, reviewed/enabled `aga_review` и loopback
  AGA MCP с ровно 4 tools.

## Safety и ограничения

- Клиент не передаёт MCP произвольный filesystem path: review идёт
  только по registered revision/case.
- Schema/import/agent errors дают `incomplete`/`error`, а не `approve`, когда
  результат проходит через AGA finalize boundary. Полный live Ouroboros loop
  проверен технически, но frozen semantic gate выявил два unsafe approve и
  поэтому остаётся fail-closed для релиза.
- Semantic findings принимаются только по strict JSON schema,
  allowlist rules/source refs и evidence из переданного snapshot.
- В OpenRouter разрешены только `synthetic-public` inputs; raw prompts,
  provider payloads, secrets и absolute local paths в evidence запрещены.
- Merge и применение evolution candidate остаются только за
  человеком.
- GitHub Actions major tags, Docker base-image tags и Python wheels пока не
  content-addressed. До release владелец должен проверить и закрепить
  action SHAs, image/OS-package digests и artifact hashes; текущие exact-claims
  ограничены Git commit pins, package versions и npm lock integrity.

Текущий handoff:
[`docs/CURRENT-STATUS-AND-NEXT-STEPS.md`](docs/CURRENT-STATUS-AND-NEXT-STEPS.md).
Supply-chain и rollback: [`THIRD_PARTY.md`](THIRD_PARTY.md).
MCP correlation/deployment contract: [`docs/MCP-CONTRACT.md`](docs/MCP-CONTRACT.md).
