# AGA: внешний enforcement checklist

Локальный MVP реализует validation, policy guard, fitness, hashes, dry-run
publisher и HITL-контракт. Эти механизмы **не заменяют** настройки репозитория
и оркестратора. В текущей рабочей папке локальный Git-root инициализирован,
но project `HEAD`, remote, public URL и platform controls отсутствуют;
поэтому пункты ниже имеют статус `external action required`.

## Репозиторий и CI

- [ ] Опубликовать код в публичном репозитории и проверить ссылку без авторизации.
- [ ] Защитить main: запрет direct push/force-push/delete, merge только через PR.
- [ ] Добавить CODEOWNERS для `evolver/fitness.py`, `evolver/permissions.yaml`,
  `evolver/mutations.py`, `evolver/policy.py`, `golden/corpus.yaml`,
  `golden/corpus.lock.json`, `golden/prs/**`, `fixtures/seaf.yaml`,
  `rules/severity-policy.yaml`,
  `SKILL.md`.
- [ ] Требовать human CODEOWNER review и успешные `make test` + `make demo`.
- [ ] Проверять неизменность existing `expected`, error weights и auto-merge
  инварианта отдельным required check.
- [ ] Проверять `patch --dry-run` для `build/rules.diff`.

## Identity и публикация

- [ ] Выдать evolver отдельную identity/token только на candidate branch.
- [ ] Запретить этой identity merge, approve и push в main на уровне платформы.
- [ ] Подключить draft-PR adapter после contract test; default оставить dry-run.
- [ ] Хранить audit logs в append-only/retention-enabled хранилище.

## Ouroboros / ГигаАгент

- [ ] Получить фактический API contract `schedule_task/wait/get` конкретной версии;
  не подменять его local backend.
- [ ] Подключить реальные diagram/SEAF/principles/ADR tasks и проверить timeout/error.
- [ ] Подключить ГигаАгент как ключевой semantic reviewer/evolution orchestrator,
  зафиксировать версию/config и доказать E2E без публикации секретов.
- [ ] Проверить network allowlist, timeout, response size, JSON schema и redaction.
- [ ] Записать озвученное демо строго короче 180 секунд с реальным ГигаАгентом.

## Приёмка администратора

Сохранить ссылки/скриншоты branch rules, CODEOWNERS, required checks, identity
permissions, draft PR и GigaAgent run. До этого документация проекта должна
говорить «local/fake backend» и «external integration required».
