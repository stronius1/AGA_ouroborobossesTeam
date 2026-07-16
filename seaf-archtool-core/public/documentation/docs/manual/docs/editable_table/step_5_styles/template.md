# ⚠️ Важные особенности ⚠️

Все стили для таблицы описываются по аналогии `css-inline` стилями, в camelCase нотации

Описать стили для таблицы можно при помощи установки для заголовка свойств:

- `style` - Позволяет установить дефолтные стили
- `styles` - Позволяет установить как дефолтные так и условные стили

# `style`

При использовании `style` возможно сразу начать добавлять стили:

```yaml
headers:
  - value: name
    style:
      backgroundColor: blue # цвет фона
```

# `styles`

Содержит объект со стилями. 

```yaml
headers:
  - value: name
    styles:
      blue-background:
        backgroundColor: blue   # цвет фона
      red-font:
        color: red              # цвет текста
```

Кроме того, мы можем установить условия для различных стилей добавив опцию `conditions`

```yaml
docs:
  archtool.plugins.editable-table.styles.table:
    type: editable-table

    origin:
      body: >
        ({
          "row_1": {"name": "Иван"},
          "row_2": {"name": "Сергей"},
          "row_3": {"name": "Петр"},
          "row_4": {"name": "Андрей"},
          "row_5": {"name": "Ольга"},
          "row_6": {"name": "Сергей"}
        })

    headers:
      - value: name
        styles:
          default-background:
            backgroundColor: orange   # цвет фона
            fontStyle: italic;        # стиль текста
          blue-background-for-ivan-and-olga:
            backgroundColor: blue     # цвет фона
            color: white              # цвет текста
            conditions:
              - condition_type: includes
                value: Иван
              - condition_type: includes
                value: Ольга
          green-background-for-sergey:
            backgroundColor: green    # цвет фона
            fontWeight: 800;          # насыщенность текста
            conditions:
              - condition_type: includes
                value: Сергей

    source: >
      ({ "body": body })
```

⚠️ Важные особенности ⚠️

Порядок описания стилей имеет значение! Первая группа стилей имеет более высокий приоритет.
Как можно заметить, для группы `default-background` не указаны условия применения `conditions`. 
Это значит что стили будут применены для всех значений.

Рассмотрим подробнее.

Допустим, ячейка содержит значение `Иван Ольга Сергей`, подходящее по каждому из описанных условий:

1. `default-background`. 

Текущие стили:

```yaml
backgroundColor: orange;
fontStyle: italic;
```

2. `blue-background-for-ivan-and-olga`. 

Текущие стили:

```yaml
backgroundColor: blue;  # перезаписан
fontStyle: italic;      # не изменился
color: white;           # добавлен
```

3. `green-background-for-sergey`.

Текущие стили:

```yaml
backgroundColor: green; # перезаписан
fontStyle: italic;      # не изменился
color: white;           # не изменился
fontWeight: 800;        # добавлен
```

![](@document/archtool.plugins.editable-table.styles.table)

Рассмотрим каждое свойство более подробно

## `conditions`

`conditions` - список применяемых условий

### `value`

`value` - значение, применяемое для проверки (текст, число, регулярное выражение)

### `condition_type`

`condition_type` - тип условия

Допустимые значения:

- equal - сравнение
- includes - проверка наличия подстроки
- match - регулярное выражение
- ">" - Больше (Обязательно в кавычках)
- ">=" - Больше или равно (Обязательно в кавычках)
- "<" - Меньше (Обязательно в кавычках)
- "<=" - Меньше или равно (Обязательно в кавычках)
