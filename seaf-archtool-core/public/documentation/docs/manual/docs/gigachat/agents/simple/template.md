# `Simple` - агент

# Описание

Агент позволяет взаимодействовать с GigaChat по [API](https://developers.sber.ru/docs/ru/gigachat/api/overview).

# ⚠️ Доступность ⚠️

Агент доступен в:

- `plugin`-mode
- `backend`-mode

# Знакомство

Познакомимся с первым агентом, опишем структуру документа:

```yaml
docs:
  archtool.plugins.gigachat.agents:
    type: ai-chat
    location: SEAF.ArchTool/Руководство/Документы/GigaChat/3. Пример
    scenarios:
      consultant:
        title: Консультант
        type: simple
        system_prompt: Ты архитектор ИТ инфраструктуры, консультируй пользователя по решениям.
        model: GigaChat-2
        query: >
          (
            $.docs."archtool.plugins.gigachat.agents"."scenarios"."consultant"
          )
```

# Базовое описание

## `system_prompt`

Основной промпт

## `model`

Название модели, от которой нужно получить ответ

## `query`

JSONata выражение, применится к озеру данных. Добавляет результат выполнения выражения, в качестве контекста, к основному промпту.

## `temperature`

Необязательный параметр.

Температура выборки в диапазоне от ноля до двух (число).

## `topP`

Необязательный параметр.

Альтернатива параметру температуры (число).

## `maxTokens`

Необязательный параметр.

Максимальное количество токенов, которые будут использованы для создания ответов (число).

# Пример формирования запроса

Рассмотрим механнику запроса детально.

В нашем примере:

`system_prompt`:

```
  Ты архитектор ИТ инфраструктуры, консультируй пользователя по решениям.
```

`query`:

```yaml
query: >
  (
    $.docs."archtool.plugins.gigachat.agents"."scenarios"."consultant"
  )
```

Выполнение данного выражение вернет нам сам документ:

```json
{
  "title": "Консультант",
  "type": "simple",
  "system_prompt": "Ты архитектор ИТ инфраструктуры, консультируй пользователя по решениям.",
  "model": "GigaChat-2",
  "query": "(\n  $.docs.\"archtool.plugins.gigachat.agents\".\"scenarios\".\"consultant\"\n)\n"
}
```

В результате, будет сформирован системный промпт для llm:

```
Ты архитектор ИТ инфраструктуры, консультируй пользователя по решениям.

Контекст, полученный из базы знаний:
{
  "title": "Консультант",
  "type": "simple",
  "system_prompt": "Ты архитектор ИТ инфраструктуры, консультируй пользователя по решениям.",
  "model": "GigaChat-2",
  "query": "(\n  $.docs.\"archtool.plugins.gigachat.agents\".\"scenarios\".\"consultant\"\n)\n"
}
```
