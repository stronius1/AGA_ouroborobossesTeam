# Golden-корпус: материализованные PR-ы

Материализованы все 26 из 26 кейсов (`pr-01` … `pr-26`). Для каждого кейса
создан реальный каталог с `meta.yaml` и состоянием артефактов после изменения;
в `corpus.yaml` все 26 записей имеют `materialized: true`.

`pr-17`…`pr-26` — отдельные positive regression cases для ранее
непокрытых deterministic-правил. Итоговая матрица: **20/20**
deterministic-правил и **17/17** operator shapes имеют positive и
negative coverage. LLM-правила в этот denominator не входят.

## Структура PR-каталога

```
golden/prs/pr-NN/
├── meta.yaml            # id, title, changed_files, context_files
└── files/               # состояние затронутых файлов ПОСЛЕ изменения
    ├── systems/AS-XXXX.md
    ├── flows/IF-XXXX.md
    ├── adrs/ADR-XXXX.md
    └── diagrams/*.puml|*.mmd
```

## Форматы артефактов (frontmatter)

Паспорт АС (`systems/`): kind, id, name, owner, criticality, target_status.
Поток (`flows/`): kind, id, source, target, pattern
(api_gateway|esb|mq|file|direct_db), zone (internal|dmz|external),
data_categories (может содержать pdn), approvals (может содержать dpo).
ADR (`adrs/`): kind, id, status, date, author, systems + секции
«## Контекст / Решение / Альтернативы / Последствия».
Диаграммы: PlantUML c `' c4: <level>` или Mermaid c `%% c4: <level>`;
узлы подписаны кодами AS-NNNN; инфраузлы (шина/шлюз) прозрачны для сверки
потоков.

`context_files` — файлы, присутствующие для кросс-проверок (SEAF-006 /
DIAG-005), но не ревьюируемые сами.
