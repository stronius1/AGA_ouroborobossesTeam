# Changelog

## v2.0.0 — 2026-07-15
- Движок стал rules-driven: `scope`, `check_type` и валидируемый `detect`
  управляют исполнением без привязки поведения к `rule_id`.
- Введены fail-closed YAML/frontmatter/path boundaries, безопасный LLM
  contract, canonical dedup, исправленные PlantUML/Mermaid parsers и обход
  инфраструктурного графа без глубинного cutoff.
- Fitness v2 сопоставляет severity/артефакт/дефект, публикует per-severity
  метрики и hashes; corpus содержит 26 исполняемых offline cases с покрытием
  20/20 deterministic rules и 17/17 operator shapes.
- Mutation validation, runtime policy guard, protected corpus lock,
  candidate-only evolver, dry-run publisher, append-only feedback и local A2A
  покрыты offline tests. Реальные CI/Ouroboros/GigaAgent/PR интеграции вынесены
  в внешний checklist и не заявляются как подключённые.

## v1.0.0 — 2026-07-14
- Сид-версия skill-пакета: 24 правила (PRIN 8, SEAF 6, DIAG 6, ADR 4),
  severity-policy, SEAF-fixture (15 систем), golden-корпус (15 кейсов,
  5 материализовано), эволвер с fitness-гейтом и SoD.
