# Реализация поиска SEAF.ArchTool

Документ описывает реализацию трёхшагового поиска объектов в хранилище архитектуры SEAF.ArchTool: backend API, frontend компоненты, конфигурация и особенности работы.

## Обзор архитектуры

Поиск реализован как трёхшаговая последовательность:

1. **Шаг 1** — выбор сущности для поиска (или «Все» для полнотекстового поиска).
2. **Шаг 2** — получение полей для фильтрации выбранной сущности.
3. **Шаг 3** — выполнение поиска с фильтрами и получение результатов.

```
 ┌─────────────────┐ GET /searchable-entities ┌─────────────────┐
 │                 │ ───────────────────────► │   Список        │
 │  Frontend       │                          │   сущностей     │
 │  Search.vue     │ ◄─────────────────────── │   (entities)    │
 └────────┬────────┘                          └─────────────────┘
          │
          │  GET /entity-filters?choice=...
          ▼
 ┌─────────────────────┐ GET /rel-suggestions ┌─────────────────┐
 │ FilterInput.vue     │ ◄─────────────────── │  Поля фильтров  │
 │ (rel → autocomplete)│                      │  (FilterField)  │
 └─────────┬───────────┘                      └─────────────────┘
           │
           │  POST /search-run { choice, filters, searchQuery? }
           ▼
 ┌─────────────────┐                      ┌─────────────────────┐
 │  Результаты     │ ◄─────────────────── │   Найденные         │
 │  v-data-table   │                      │   объекты (≤10 000) │
 └─────────────────┘                      └─────────────────────┘
```

## Конфигурация

### Манифест плагина (seaf.yaml)

В корневом манифесте плагина можно ограничить список сущностей, по которым выполняется поиск:

```yaml
search:
  entities:
    - id: kadzo.v2023.application.systems
    - id: kadzo.v2023.integrations
      dataset: kadzo.v2023.integrations
```

- `id` — идентификатор сущности (обязателен).
- `dataset` — опциональный идентификатор датасета из `manifest.datasets`. Если не задан, данные берутся из озера (`manifest[id]`).
- Если `search.entities` не задан — используются все сущности с `schema`, `title` и данными в озере.
- Если задан — поиск выполняется только по указанным сущностям.

### Данные в датасетах

Если для сущности указан `dataset`, объекты загружаются через драйвер датасетов (`releaseData`). Результат датасета **зеркалирует структуру озера**:

```yaml
kadzo.v2023.application.systems:
  ecogroup.system1:
    title: ...
  ecogroup.system2:
    title: ...
```

Поиск использует срез `datasetResult[id]` — тот же формат, что `manifest[id]` при хранении в озере.

Схемы сущностей (`manifest.entities[id].schema`) по-прежнему читаются из озера.

### Модули загрузки данных

- **`search-config.mjs`** — парсинг `search.entities`, определение источника данных.
- **`search-data.mjs`** — `SearchDataProvider` с кэшем; `extractEntityObjects(source, entityId)` извлекает map объектов из озера или датасета.

## Backend

### Контроллер

**Файл:** `src/backend/controllers/search.mjs`

Регистрирует маршруты:

| Метод | Путь | Описание |
|-------|------|----------|
| GET   | `/seaf-core/api/core/storage/search/searchable-entities`        | Список сущностей для поиска |
| GET   | `/seaf-core/api/core/storage/search/entity-filters`       | Поля для фильтрации сущности |
| GET   | `/seaf-core/api/core/storage/search/rel-suggestions` | Подсказки для полей типа rel |
| POST  | `/seaf-core/api/core/storage/search/search-run`        | Выполнение поиска |

### Основные функции

- **`getSearchableEntities(manifest)`** — список сущностей для поиска с учётом `search.entities` (озеро или датасет).
- **`SearchDataProvider`** — загрузка данных сущности из озера или датасета с кэшированием.
- **`extractEntityObjects(source, entityId)`** — извлечение map объектов из озера/датасета.
- **`collectRelFields(fullSchema, choice, manifest)`** — поля-ссылки (`$ref` на `#/$rels/`) в схеме сущности.
- **`filterValue(params)`** — проверка объекта по массиву фильтров (логика AND).
- **`resolveRefTitles(manifest, relTarget, ids, entityDataMap?)`** — получение названий связанных объектов для фильтрации по rel (с учётом предзагруженных данных датасетов).
- **`buildSearchResultItem(...)`** — формирование элемента результата с полями `_sfa_key`, `_sfa_entity`, `company`, `title`, `description`, `card`.

### Логика фильтрации

- Все фильтры объединяются по **AND**.
- Поддерживаемые операторы: `eq`, `gt`, `gte`, `lt`, `lte`, `contains`, `startsWith`, `endsWith`, `in`, `between`, `exists`.
- Для полей-ссылок (rel): поиск по title и aliases связанных объектов; операторы `contains`, `eq`, `startsWith`, `endsWith`, `exists`.
- Флаг `ignoreCase` — регистронезависимый поиск для строк.
- Флаг `not` — инвертирование условия.
- Лимит результатов: **10 000** (`SEARCH_RESULT_LIMIT`).

### Режим «Все» (choice=__all__)

При `choice: '__all__'`:

- Фильтры не применяются (массив `filters` пустой).
- Используется `searchQuery` — слова ищутся в `title` и `description` объектов.
- Поиск выполняется по всем поисковым сущностям.

## Frontend

### Компоненты

**Search.vue** (`src/frontend/components/Search/Search.vue`)

- Загрузка сущностей (`/searchable-entities`).
- `SearchDataProvider` в non-backend режиме — загрузка датасетов через `datasets().releaseData()`.
- Переключатель сущностей (chips).
- Строка поиска (`searchQuery`).
- Панель фильтров (правая колонка).
- Таблица результатов (`v-data-table`).
- Построение массива фильтров: `buildFiltersArray()` — маппинг значений из `filters` в объекты `{ field, operator, value, ignoreCase }`.

**FilterInput.vue** (`src/frontend/components/Search/FilterInput.vue`)

- Один компонент на каждое поле фильтра.
- Типы полей и соответствующие элементы:
  - `string` — `v-text-field`
  - `number`, `integer` — `v-text-field` с `type="number"`
  - `enum` — `v-select` по `enumValues`
  - `rel` — `v-text-field` с автодополнением (`/rel-suggestions`)
- Для rel: debounce 300 мс при вводе, запрос подсказок по `relTarget` и `query`.

### Последовательность вызовов

1. При монтировании: `loadEntities()` → GET `/searchable-entities`.
2. При выборе сущности (кроме «Все»): `loadFilterFields(choice)` → GET `/entity-filters?choice=...`.
3. При вводе в поле типа rel: debounce → GET `/rel-suggestions?relTarget=...&query=...` (данные rel-сущности из озера или датасета по конфигу).
4. При поиске (кнопка «Найти» или Enter): `performSearch()` → POST `/search-run` с `{ choice, filters, searchQuery }`.

### Маппинг операторов (Search.vue)

| Тип поля | Оператор | Примечание |
|----------|----------|------------|
| string   | `contains` | `ignoreCase: true` |
| rel      | `contains` | `ignoreCase: true` |
| number, integer | `eq` | `value` приводится к Number |
| enum     | `eq` | Значение как есть |

Текстовый запрос (`searchQuery`) при выборе конкретной сущности: первый строковый/enum-поле (title/name/label) — `contains` по `searchQuery`.

## Схема сущности и поля для поиска

Поля для фильтрации извлекаются из JSON Schema сущности:

- **string, number, integer** — свойства с `type`.
- **enum** — свойства с `enum` (без `type` или с `type: string`).
- **rel** — свойства со ссылками `$ref: "#/$rels/entityId.subjectId"` (включая вложенные через `$defs`, `items`).

Для rel формат `relTarget` — `entityId.subjectId` (например, `kadzo.v2023.groups.groups`).

## API спецификация

Полное описание эндпоинтов, схем запросов/ответов и примеров см. в:

- [Search API (OpenAPI)](/entities/docs/blank?dh-doc-id=archtool.backend.search)

## Результаты поиска

Каждый элемент результата содержит:

| Поле         | Описание                              |
|--------------|----------------------------------------|
| `_sfa_key`   | Уникальный ключ объекта                |
| `_sfa_entity`| Идентификатор сущности                |
| `company`    | Название организации (если есть)      |
| `entityTitle`| Название типа сущности                |
| `title`      | Заголовок объекта                     |
| `description`| Описание                              |
| `card`       | URL карточки (если есть presentation) |
| `...value`   | Все остальные поля объекта            |

Колонка «Компания» отображается в таблице, если `hasCompanies === true` в ответе `/first`.
