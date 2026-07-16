---
id: "0001"
date: 2026-07-10
pr: golden/prs/pr-15
rule_id: PRIN-002
agent_finding: {severity: major, evidence: "pattern: file — файловый обмен вне утверждённых паттернов"}
architect_action: override
architect: "И. Петров, домен «Интеграции»"
rationale: >
  Файловый обмен в DMZ-сегменте разрешён регламентом ИБ-2024-17 для
  batch-выгрузок: канал контролируется файловым шлюзом, наблюдаемость
  обеспечена. Запрет PRIN-002 относится к неуправляемому обмену внутри
  контура, а не к этому классу потоков.
proposed_mutation:
  type: add_exception
  provenance: "precedent:0001"
  rule_id: PRIN-002
  exception:
    when:
      all:
        - {field: zone, equals: dmz}
        - {field: pattern, equals: file}
        - {field: transfer_mode, equals: batch}
        - {field: gateway_controlled, equals: true}
        - {field: approvals, contains: security}
    rationale: >
      Файловый обмен допустим только как контролируемая batch-выгрузка через
      файловый шлюз DMZ по регламенту ИБ-2024-17.
    provenance: "precedent:0001"
golden_case: pr-15
status: pending
---
# Прецедент 0001: файловый batch-обмен в DMZ

Агент выставил major по PRIN-002 на поток IF-0104 (АБС → ECM, pattern: file,
zone: dmz). Архитектор переопределил вердикт со ссылкой на ИБ-2024-17.
Кейс pr-15 добавлен в golden-корпус с ground truth = approve.
