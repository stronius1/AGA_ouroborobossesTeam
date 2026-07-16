# Технологии (technologies)

Важным процессом в управлении архитектурой является управление технологическим стеком. SEAF.ArchTool позволяет решить
эту задачу через манифесты технологического стека. В манифесте перечисляются технологии и их статус.

```yaml
technologies:                   # Описание технологического стека
    sections:                   # Определение разделов стека
        language:               # Идентификатор раздела
            title: Языки программирования   # Название раздела
        parsers:
            title: Парсеры
        tools:
            title: Инструментарий
        storages:
            title: Хранилища
        browsers:
            title: Браузеры
    items:                      # Перечисление технологий
        JavaScript:             # Идентификатор технологии
            aliases:            # Синонимы технологии
                - js
                - NodeJS
            title: Супер-крутой язык программирования           # Название технологии
            link: https://ru.wikipedia.org/wiki/JavaScript      # Ссылка на документацию
            section: language   # Идентификатор секции технологии
            status: adopt       # Статус технологии adopt / trial / assess / hold
```

```yaml
title: Рабочая\nобласть
entity: component
source_file: src/components/Root.vue
technologies:                   # Используемые технологии
  - JavaScript
  - VUE3
links:
  - id: archtool.router
    title: Представление
    direction: -->
  - id: archtool.router
    title: Параметры
    direction: <--
```

Описанные технологии также являются архитектурными объектами и имеют карточки. 
Например, карточка для JavaScript:

![Карточка технологии](@technology/JavaScript)
