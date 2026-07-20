# Demo video script · 2:55

Цель: за 175 секунд показать проблему, полный фактический E2E, роль Ouroboros,
вход/выход и safety boundary. Числа сверяются с
[`SUBMISSION-FACTS.json`](SUBMISSION-FACTS.json). Видео обязательно записывается
с голосом; ускорение допустимо только для ожидания, а не для подмены результата.

## До записи

```bash
make demo-verify
make self-evolution-ui
```

- Открыть `http://127.0.0.1:8090` в чистом окне.
- Выбрать Full preset, фиксированный seed и Local `$0` для воспроизводимого
  полного E2E.
- Если в видео запускается Live: отдельно выполнить preflight и получить явное
  разрешение владельца на paid OpenRouter calls. Не выдавать replay/retained
  evidence за новый live call.
- Убедиться, что экран Result показывает пять checks, `human review required`
  и `merge=false`.

## Тайминг и озвучка

| Время | Экран | Текст голоса |
|---|---|---|
| 0:00–0:18 | Заголовок + AS IS | «Архитектурные PR нужно постоянно сверять с SEAF, ADR, диаграммами и принципами. Ручной review создаёт очередь и неодинаковые комментарии. AGA превращает эту работу в проверяемый advisory pipeline.» |
| 0:18–0:35 | Короткая схема | «Trusted host строит snapshot base/head и выполняет guardrails. Ouroboros через AGA MCP делает semantic review. Ни модель, ни агент не получают права push, approve или merge.» |
| 0:35–0:48 | Создание scenario | «Запускаю бесплатный полный E2E. Новый synthetic-public scenario генерируется сейчас: 11 узлов, 9 потоков и 26 materialized golden cases.» |
| 0:48–1:17 | Architecture lane | «Review обнаруживает SEAF-004: новый поток ведёт в legacy-компонент со статусом eliminate. Remediation использует только явно объявленный successor и меняет одну цель потока. Re-review подтверждает, что finding закрыт и новых нарушений нет.» |
| 1:17–1:43 | Rules/tests | «Параллельно candidate правила проверяется на тех же 26 кейсах. Baseline проходил 25 из 26; candidate — 26 из 26. Изменился только согласованный DMZ case pr-15, а опасный negative control pr-16 остался заблокированным.» |
| 1:43–2:05 | Agents/events | «Это не заранее записанный результат: видны реальные стадии, воркеры, входные artifacts и baseline/candidate outcomes. Пять независимых checks сходятся в unified safety gate.» |
| 2:05–2:25 | Result | «Gate прошёл: workspace валиден, SEAF-004 закрыт, candidate tests совпали с oracle, регрессий нет и улучшение строгое. Результат остаётся локальным candidate: human review обязателен, merge не выполнялся.» |
| 2:25–2:42 | Retained live evidence | «Ouroboros сыграл ключевую роль в отдельном controlled live E2E: три реальные задачи review, remediation и re-review оставили MCP receipts, task ID и суммарную стоимость 0.113183 доллара.» |
| 2:42–2:55 | Ограничения + финал | «Мы не смешиваем метрики: исторический broad semantic freeze получил FAIL, нового release PASS пока нет. Следующий шаг — human review 48-case development-v2, пять стабильных повторов, новый holdout и shadow pilot.» |

## Обязательные кадры

- входной граф до изменения;
- finding `SEAF-004` с exact artifact/location;
- однострочный patch `legacy_scoring → scoring_v2`;
- re-review без целевого finding;
- `pr-15` и `pr-16` рядом;
- 26 candidate outcomes;
- все пять checks gate;
- task IDs/MCP receipts/model cost controlled live evidence;
- `human_review_required=true`, `auto_merge=false`;
- финальная формулировка historical semantic `FAIL`, не PASS.

## Монтажный запрет

Нельзя склеивать вход одного run с результатом другого без явной подписи,
называть Local режим Live, скрывать failed lane общим процентом, показывать
fixture `16/16` как model quality или оставлять на экране private path/key.

Публичный video URL пока не опубликован; после загрузки его нужно записать в
`publication.demo_video_url` файла `SUBMISSION-FACTS.json` и синхронизировать
README/Project Results.
