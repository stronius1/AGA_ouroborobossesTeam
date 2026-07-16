# Описание

Чат для взаимодействия с ИИ-агентом

# Начинающим пользователям

Рекомендуем ознакомиться с основными концепциями:

- [1. Настройка](/entities/docs/blank?dh-doc-id=archtool.plugins.gigachat.settings.menu)
- [2. Агенты](/entities/docs/blank?dh-doc-id=archtool.plugins.gigachat.agents.menu)

# Базовое описание

Рассмотрим основные свойства документа:

```yaml
archtool.plugins.gigachat.example:
  type: ai-chat
  scenarios:
    scenarios_id_1:
      title: Сценарий 1
      type: simple
      # описание агента, с ними мы познакомимся позже
    scenarios_id_2:
      title: Сценарий 2
      type: react
      # ...
```

Рассмотрим свойства детально:

`type: ai-chat` - идентификатор документа `ai-chat`

`scenarios` - подключаемые к документу сценарии (агенты)

Таким образом, мы получим интерфейс чата, с возможностью переключения между сценариями.

Познакомимся с [агентами](/entities/docs/blank?dh-doc-id=archtool.plugins.gigachat.agents.menu)
