# Финальный submission checklist

Чеклист не объявляет незавершённые внешние действия выполненными. Канонические
цифры и public URLs: [`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json).

## Автоматические локальные gates

- [x] `make demo-verify` завершён кодом 0 без paid/network calls.
- [x] `make project-results-check` завершён кодом 0.
- [x] `make submission-consistency-check` завершён кодом 0.
- [x] `make check-secrets` завершён кодом 0.
- [x] `make verify-development-v2` завершён кодом 0 без model calls; human
  review/paid measurement при этом честно остаются pending.
- [x] После проверок отсутствуют `.DS_Store`, `__pycache__`, `.pytest_cache` и
  `*.pyc`.
- [x] Известные supply-chain gaps закрыты immutable pins; checker не выдаёт
  supply-chain warnings.

## Чистый публичный repository

- [x] Создан public remote; URL записан в
  `publication.public_repository_url`
  (`https://github.com/stronius1/AGA_ouroborobossesTeam`).
- [x] Submission commit содержит все required файлы, новые docs и evidence
  (`docs/evidence/ouroboros-self-evolution-v1.json` присутствует —
  результаты, а не только код).
- [x] Submodule revisions доступны публичному клонировщику и совпадают с pins
  (проверено clean-clone: `seaf-core`@`60ce335`, `seaf-archtool-core`@`83c82ab`).
- [x] GitHub Actions закреплены commit SHA, container base image — digest.
- [x] Python wheels для CI/container снабжены SHA-256 и устанавливаются через
  `--require-hashes`.
- [x] OS packages берутся из датированного Debian snapshot.
- [x] В отдельном временном каталоге выполнены `git clone --recurse-submodules`,
  fresh venv, `make verify-pins` и `make demo-verify` — оба EXIT 0.
- [x] После clean-clone verification `git status --short` пуст.
- [ ] Проверены LICENSE/THIRD_PARTY и отсутствие private profile settings,
  credentials, local paths и sensitive PDF metadata/content — root `LICENSE`
  всё ещё отсутствует, выбор лицензии за владельцем (см. блокер ниже).

## Project Results и презентация

- [x] [`PROJECT-RESULTS.md`](PROJECT-RESULTS.md) экспортирован в читаемый
  [`AGA-Ouroboros-Project-Results.pdf`](AGA-Ouroboros-Project-Results.pdf).
- [ ] Public PDF URL записан в `publication.project_results_pdf_url`.
- [x] [`PROPOSAL-TRACEABILITY.md`](PROPOSAL-TRACEABILITY.md) заполнен без
  скрытых расхождений `13→26`, `15→11`, auto-approve→advisory.
- [x] [`BUSINESS-EFFECT.md`](BUSINESS-EFFECT.md) содержит исходные допущения,
  формулу и sensitivity; `4.1 млн ₽/15×` помечены как hypothesis.
- [x] [`AGA-Ouroboros-Project-Results.pptx`](AGA-Ouroboros-Project-Results.pptx)
  следует [`PRESENTATION-OUTLINE.md`](PRESENTATION-OUTLINE.md); восемь слайдов
  содержат по одному выводу.
- [x] README, report, deck и video используют один measurement boundary и
  одинаковые числа.

## Demo video

- [ ] Сценарий следует [`DEMO-VIDEO-SCRIPT.md`](DEMO-VIDEO-SCRIPT.md).
- [ ] Длительность строго меньше 180 секунд.
- [ ] Есть разборчивая голосовая озвучка.
- [ ] Видны вход, review, remediation, re-review, 26 tests, пять gate checks и
  выход.
- [ ] Local/Live/replay/retained evidence подписаны правдиво.
- [ ] Видны task IDs, MCP receipts, model/cost, HITL и `merge=false`.
- [ ] Historical semantic frozen `FAIL` не назван release PASS.
- [ ] Видео открывается без авторизации; URL записан в
  `publication.demo_video_url`.

## Ручной narrative audit

- [ ] Независимый reviewer за 30 секунд отвечает: боль, роль Ouroboros, E2E,
  результат, safety и ограничение.
- [ ] Deterministic 26-case, controlled live E2E, fixture 16-case и historical
  semantic FAIL не смешаны.
- [ ] Advisory approve нигде не назван repository auto-approve/merge.
- [ ] Business case нигде не назван измеренным production ROI.
- [ ] Все Markdown/PDF/video/repository ссылки открыты из приватного окна.

## Отправка

- [ ] Проверены точные адрес, тема, формат письма/формы и deadline организатора.
- [ ] Приложены public repository, Project Results PDF, deck и video URL.
- [ ] Отправка выполнена заранее; сохранены timestamp и подтверждение доставки.

## Текущие внешние блокеры на 20 июля 2026

- [x] Public repository URL: `https://github.com/stronius1/AGA_ouroborobossesTeam`.
- [ ] Demo video URL отсутствует.
- [ ] Public Project Results PDF URL отсутствует; локальный PDF собран.
- [x] Public clean-clone verification выполнена (`/tmp/clean-clone-test`:
  submodules OK, `make verify-pins` OK, `make demo-verify` EXIT 0,
  `git status --short` пуст).
- [ ] Root `LICENSE` отсутствует; вариант лицензирования должен выбрать
  владелец до публикации.
- [ ] Independent human review, freeze и пять прогонов development-v2 не
  выполнены.
- [ ] Docker build rehearsal не выполнен: на текущей машине daemon недоступен.
- [ ] ArchTool `npm test`/`backend-build` не выполнены на текущей машине:
  Node/npm отсутствуют; Python SEAF tests и workspace validation прошли.
- [ ] Browser visual/click rehearsal не выполнен: in-app browser backend в
  текущей сессии недоступен; loopback UI contracts прошли автоматически.
- [ ] Семь локальных `docs/evidence/ui/*.json` нужно явно включить как отдельную
  серию или исключить из submission scope; canonical facts на них не ссылаются.
- [ ] Для organizer PDFs и внутренних plan/prompt/notes подтверждены права и
  принято явное решение include/exclude до `git add -A`.
- [ ] Новый trusted broad semantic release PASS отсутствует; старый holdout
  раскрыт и повторно использоваться не должен.
