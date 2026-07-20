# 🧬 Эволюция skill: v{{version_from}} → v{{version_to}}

**Локальная candidate-ветка:** `{{branch}}` · **Дата:** {{date}} · **Мутация:** `{{mutation_type}}` → {{rule_id}}
**Provenance:** {{precedent}}

## Мотивация (обоснование архитектора)

> {{rationale}}

## Diff правил

```diff
{{diff}}
```

## Метрики на golden-корпусе

{{metrics_table}}

## Атомарная candidate-транзакция

Локальный commit содержит только изменённые rule-файлы, `VERSION`, полную
запись `CHANGELOG.md`, distilled precedent и эти проверяемые report/evidence.
Исходные HEAD, index и working tree не изменяются. Push, PR, approve и merge
этим контуром не выполняются.

## Чек-лист перед merge (человек)

- [ ] Обоснование прецедента корректно и общо (не разовый случай)
- [ ] Исключение не создаёт лазейку для обхода правила
- [ ] Дельта метрик соответствует ожиданиям
- [ ] Откат при необходимости: `git revert` этого merge-коммита

*Сгенерировано aga-evolver как локальный candidate artifact. Candidate commit
создаёт отдельный local-only connector; review и любой merge выполняет только
человек (SoD).*
