# AGA governance (сид-топик для knowledge base Ouroboros)

Когда задача касается архитектурного ревью, PR с архитектурными артефактами,
SEAF-консистентности или ADR — загрузи skill `aga-review` (SKILL.md пакета
aga-skill) и используй инструменты aga_review_pr / aga_parse_diagram /
aga_seaf_lookup. Эволюция правил — отдельная candidate-only роль aga-evolver
(evolver/EVOLVER.md), запускается только по расписанию или командой владельца.

Локальный A2A backend, dry-run publisher и trusted Ouroboros `v6.64.1` backend
реализованы. Реальный synthetic-public tool path технически проверен, но frozen
semantic gate получил `FAIL`, поэтому не выдавай его за release evidence и не
повторяй тот же holdout. VCS и draft-PR adapters требуют внешней интеграции; не
подменяй их fake backend. После CLI review атомарная запись появляется в
`logs/reviews.jsonl` (схема — SKILL.md §8).
