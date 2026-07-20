# Прецеденты — сырьё эволюции

Прецедент — зафиксированное расхождение между вердиктом агента и решением
архитектора. Это «прецедентное право» governance: накапливается в ревью,
дистиллируется эволвером в правила/исключения (TOGAF Enterprise
Continuum в миниатюре).

## Схема (frontmatter)

| Поле | Значение |
|---|---|
| id | номер прецедента |
| pr | ссылка на PR (в демо — golden/prs/…) |
| rule_id | правило, вокруг которого расхождение (или null для missed) |
| architect_action | accept / override / edit / missed |
| rationale | обоснование архитектора — главное содержимое |
| proposed_mutation | заготовка мутации (JSON по evolver/mutations.md) |
| golden_case | id кейса, добавленного в корпус из этого прецедента |
| status | pending → distilled / rejected / backlog |
| distilled_in | версия отдельно от status; заполнена только для distilled |

## Жизненный цикл

1. Ревью → эскалация → `scripts/record_action.py` добавляет immutable human event.
2. Approved override/missed → этой же командой создаётся новый файл прецедента
   со статусом `pending`; существующий файл не перезаписывается. Без
   `--golden-case`/`--mutation-file` это intake-запись, ещё не готовая к cycle.
3. Человек отдельно утверждает и защищает golden case, затем передаёт оба
   поля вместе. Например:

   ```bash
   python3 scripts/record_action.py --review-id REVIEW --action override \
     --actor ARCHITECT --rationale POLICY --rule-id PRIN-002 \
     --precedent-id 0042 --golden-case pr-27 --mutation-file mutation.yaml
   ```

4. Эволвер проверяет pre-cycle corpus/fixture lock, затем mutation → fitness →
   candidate и dry-run publisher artifacts.
5. Candidate artifact хранит `status: distilled` и отдельный `distilled_in`.
   После независимого replay fitness/gate local-only VCS connector переносит
   его вместе с rules/VERSION/CHANGELOG только в отдельный candidate commit.
   В исходной ветке precedent остаётся `pending`, пока человек не проверит и
   не решит слить candidate; сам connector merge не выполняет.
