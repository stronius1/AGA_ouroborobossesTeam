Опишем и подключим в озеро нашу первую таблицу

```yaml
docs:
  archtool.plugins.editable-table.acquaintance.table:
    type: editable-table
    headers:
      - value: id
        width: 100px
      - value: name
        width: 200px
      - value: age
        width: 100px

    source: >
      (
          $data := {
              "row_1": {
                  "id": "0001", "name": "Иванов Иван Иванович", "age": 36
              },
              "row_2": {
                  "id": "0002", "name": "Петров Петр Петрович", "age": 19
              },
              "row_3": {
                  "id": "0003", "name": "Семенов Семен Семенович", "age": 43
              }
          };

          { "body": $data }
      )
```

Получим результат

![](@document/archtool.plugins.editable-table.acquaintance.table)

Разберем более подробно основные моменты

# Базовые параметры

Ключевым для базового описания таблицы является заполнение параметров документа `type`, `headers` и `source`;

## Свойство `type`

Указание типа создаваемого документа, где `editable-table` является идентификатором редактируемых таблиц.

## Свойство `headers`

Массив заголовков. В каждом заголовке должно быть описано уникальное значение параметра `value`.
Прочие параметры `headers` рассмотрим далее.

## Свойство `source`

JSONata выражение, результатом выполнения которого, ожидается объект содержащий следующие поля:

- `body` (обязательное) - содержит данные для наполнения таблицы
- `headers` (опциональное) - позволяет мутировать заголовки (рассмотрим подробнее ниже)

Со структурой `body` можно ознакомиться в примере выше (переменная `$data`).

# Использование `origin`

При расчете `source`, возможно использовать `origin`.
Вынесем данные для нашей таблицы в `origin`.

```yaml
archtool.plugins.editable-table.acquaintance.table_with_origin:
  type: editable-table
  origin:
    body: >
      ({
          "row_1": {
              "id": "0001", "name": "Иванов Иван Иванович", "age": 36
          },
          "row_2": {
              "id": "0002", "name": "Петров Петр Петрович", "age": 19
          },
          "row_3": {
              "id": "0003", "name": "Семенов Семен Семенович", "age": 43
          }      
      })
  headers:
    - value: id
      width: 100px
    - value: name
      width: 200px
    - value: age
      width: 100px

  source: >
    ({ "body": body })
```

И получим аналогичный результат:

![](@document/archtool.plugins.editable-table.acquaintance.table_with_origin)

# Мутация заголовков

Опишем еще один `origin` для измененных заголовков. Для существующих заголовков заменим идентификатор заголовка на понятное описание, а также добавим еще один заголовок.

```yaml
  archtool.plugins.editable-table.acquaintance.table_header_mutation:
    type: editable-table
    origin:
      updated_headers: >
        (
            $header_placeholder_map := {
                "id": "Идентификатор",
                "name": "Имя",
                "age": "Возраст"
            };    
        
            /* Получаем значение текущих заголовков из документа */
            $headers := $lookup($.docs, "archtool.plugins.editable-table.acquaintance.table_header_mutation").headers;
        
            /* Обновленные заголовки */
            $updated_headers := $map($headers, function ($v){(
                /* 
                    Для каждого заголовка:
                    - добавим отображаемое значение, указав "text"
                    - изменим ширину колонки на 200px
                */
                $placeholder := $lookup($header_placeholder_map, $v.value);
                $merge([$v, {"text": $placeholder, "width": "200px"}])
            )});
            
            /* Создадим и добавим еще один заголовок */
            $new_header := {"value": "weight", "text": "Вес", "width": "100px" };
            $append($updated_headers, $new_header) 
        )
      body: >
        ({
            "row_1": {
                "id": "0001", "name": "Иванов Иван Иванович", "age": 36, "weight": 87
            },
            "row_2": {
                "id": "0002", "name": "Петров Петр Петрович", "age": 19, "weight": 75
            },
            "row_3": {
                "id": "0003", "name": "Семенов Семен Семенович", "age": 43, "weight": 80
            }      
        })
    headers:
      - value: id
        width: 100px
      - value: name
        width: 200px
      - value: age
        width: 100px

    source: >
      (
          { "body": body, "headers": updated_headers }      
      )
```

Посмотрим на результат:

![](@document/archtool.plugins.editable-table.acquaintance.table_header_mutation)

## Механика и особенности

При указании заголовков в `source` осуществляется поиск по идентификатору данной колонки. 
Если колонка найдена происходит глубокое объединение (deep merge).
Если колонка не найдена - добавляется как новая.

Рассмотрим на примере

```yaml
  archtool.plugins.editable-table.acquaintance.table_header_mutation_2:
    type: editable-table
    filtration: false
    sorting: false
    origin:
      updated_headers: >
        ([
            { "value": "new_column_1", "text": "Новая колонка 1" }, 
            { "value": "column_3", "text": "Колонка 3 (обновлено)" },
            { "value": "new_column_2", "text": "Новая колонка 2" },
            { "value": "column_4" }
        ])
      body: >
        ({"row_1": {}})
    headers:
      - value: column_1
        text: Колонка 1
      - value: column_2
        text: Колонка 2
      - value: column_3
        text: Колонка 3
      - value: column_4
        text: Колонка 4

    source: >
      (
          { "body": body, "headers": updated_headers }      
      )
```

В таблице мы описали заголовки:

```yaml
    headers:
      - value: column_1
        text: Колонка 1
      - value: column_2
        text: Колонка 2
      - value: column_3
        text: Колонка 3
      - value: column_4
        text: Колонка 4
```

Далее мутируем их данными:

```yaml
      updated_headers: >
        ([
            { "value": "new_column_1", "text": "Новая колонка 1" }, 
            { "value": "column_3", "text": "Колонка 3 (обновлено)" },
            { "value": "new_column_2", "text": "Новая колонка 2" },
            { "value": "column_4" }
        ])
```
Рассмотрим мутацию поэтапно:

1. `{ "value": "new_column_1", "text": "Новая колонка 1" }`

    Заголовка с идентификатором (`value`) `new_column_1` не существует - заголовок добавлен как новый.

2. `{ "value": "column_3", "text": "Колонка 3 (обновлено)" }`

    Заголовок с идентификатором (`value`) `column_3` уже описан. Свойство `text` будет заменено.

3. `{ "value": "new_column_2", "text": "Новая колонка 2" }`

   Заголовок с идентификатором (`value`) `new_column_2` не существует - заголовок добавлен как новый.

4. `{ "value": "column_4" }`

   Заголовок с идентификатором (`value`) `column_4` уже описан, но другие свойства не переданы, поэтому ничего не поменяется.

Посмотрим на результат:

![](@document/archtool.plugins.editable-table.acquaintance.table_header_mutation_2)

