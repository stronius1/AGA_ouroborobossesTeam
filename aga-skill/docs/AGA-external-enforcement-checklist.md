# AGA: внешний enforcement checklist

Локальный MVP реализует validation, policy guard, fitness, hashes, dry-run
evolver и отдельный local-only candidate publisher. Внешнего Git remote в
этом проекте нет и для Loop A он не нужен: эквивалент review request —
локальная candidate-ветка, реальный commit, diff и PR-shaped report.

## Локальный репозиторий и проверки

- [x] Evolver пишет только candidate bundle и dry-run evidence в `build/`.
- [x] Publisher повторно выполняет `validate_candidate`, fitness и gate до
  materialization и связывает результат с exact base commit.
- [x] Candidate строится в disposable worktree; caller HEAD/index/worktree
  после успеха и ошибки остаются неизменны.
- [x] Один commit содержит exact allowlist: changed rules only, `VERSION`,
  полный `CHANGELOG.md`, distilled precedent и report/manifest.
- [x] Candidate ref создаётся атомарно; одинаковый повтор идемпотентен, а
  конфликтующее содержимое fail-closed.
- [ ] Человек должен проверить local diff/report и отдельно решить вопрос о
  merge; автоматический merge отсутствует.

## Роли и публикация

- Evolver не имеет create-branch/create-commit прав и заканчивает dry-run.
- `aga-local-candidate-publisher` имеет только локальные create-branch/commit
  права на exact transaction после независимой проверки.
- Обеим ролям запрещены network, push, open-PR, approve и merge.
- Для усиления OS-level SoD можно запускать роли под разными локальными
  identities; Python runtime сам по себе не является security sandbox.

## Ouroboros / ГигаАгент

- [ ] Получить фактический API contract `schedule_task/wait/get` конкретной версии;
  не подменять его local backend.
- [ ] Подключить реальные diagram/SEAF/principles/ADR tasks и проверить timeout/error.
- [ ] Подключить ГигаАгент как ключевой semantic reviewer/evolution orchestrator,
  зафиксировать версию/config и доказать E2E без публикации секретов.
- [ ] Проверить network allowlist, timeout, response size, JSON schema и redaction.
- [ ] Записать озвученное демо строго короче 180 секунд с реальным ГигаАгентом.

## Приёмка владельца

Проверить реальный local candidate SHA, `git show --stat --oneline <SHA>`,
PR-shaped report и sanitized manifest. Не придумывать URL: для local-only
outcome `draft_pr_url` всегда `null`.
