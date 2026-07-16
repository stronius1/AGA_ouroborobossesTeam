---
id: "0002"
date: 2026-07-12
pr: null
rule_id: null
architect_action: missed
architect: "О. Ким, домен «Данные»"
rationale: >
  Агент не заметил, что PR фактически вводит второй мастер клиентских
  адресов (проза в паспорте, без структурного поля). Кандидат: усиление
  PRIN-005 через отдельную LLM evaluation либо новое candidate
  deterministic-правило по полю masters_data_domain в паспорте.
proposed_mutation: null
golden_case: null
status: backlog
---
# Прецедент 0002: пропущенный второй мастер данных (backlog)

Тип missed: слепая зона LLM-проверки PRIN-005. Ждёт материализации
golden-кейса, до этого мутация не запускается (anti-Goodhart).
