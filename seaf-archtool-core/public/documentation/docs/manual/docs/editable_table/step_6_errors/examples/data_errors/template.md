# Ошибки в данных

В большинстве случаев, данные для таблицы будут сформированы в JSONata-выражением применненым на различных частях манифеста.
Это может привести к неожиданным результатам, в следствии чего данные переданные в таблице в поле `body` могут быть некорректны.
Мы можем отобразить ячейки с ошибками указав флаг `show_data_error` в корне документа.

Рассмотрим на примере. Рассмотрим таблицу.

```yaml
archtool.plugins.editable-table.errors.data_errors.table.step_1:
  type: editable-table

  origin:
    body: >
      (
          /* Представим что в поле выполняется сложное выражение */
          /* Для наглядности будут использоваться готовые данные */
          $."archtool.plugins.editable-table.errors.data_errors.data"        
      )

  headers:
    - value: text
      width: 150px

    - value: select
      type: select
      width: 150px
      options:
        - value: option_1
          text: опция 1
        - value: option_2
          text: опция 2
        - value: option_3
          text: опция 3

    - value: multiple-select
      type: multiple-select
      width: 150px
      options:
        - value: option_1
          text: опция 1
        - value: option_2
          text: опция 2
        - value: option_3
          text: опция 3

  source: >
    ({ "body": body })
```

Подготовим данные для нашей таблицы, предположим, в ходе выполнения JSONata-выражения, произошла ошибка, и мы получили данные, которые не может обработать наша таблица.

Полученные данные выглядят таким образом:

```yaml
archtool.plugins.editable-table.errors.data_errors.data:
  row_1:
    text: Строка
    select: option_1
    multiple-select:
      - option_1
      - option_3
  row_2:
    text:
    select:           # Для заголовка с типом "select" получен массив
      - item
      - item
    multiple-select:  # Для заголовка с типом "multiple" получена строка
      data: item
  row_3:
    text: Строка
    select:           # Для заголовка с типом "select" получен массив
      data: value
    multiple-select:
  row_4:
    text:             # Для заголовка с типом "text" получен массив
      - item
      - item
    select:
    multiple-select:
      - option_1
      - option_2
      - option_3
  row_5:
    text:             # Для заголовка с типом "text" получен объект
      text: Строка
      number: 123
    select: option_2
    multiple-select:
      - option_2
      - option_3
  row_6:
    text: Строка
    select: option_2
    multiple-select: option_3  # Для заголовка с типом "multiple" получена строка
```

В результате, вывод документа будет выглядеть следующим образом:

![](@document/archtool.plugins.editable-table.errors.data_errors.table.step_1)

Исправим данное поведение, выставив флаг `show_data_error: true`.
Общее описание таблицы:

```yaml
  archtool.plugins.editable-table.errors.data_errors.table.step_2:
    type: editable-table
    show_data_error: true

    origin:
      body: >
        ($."archtool.plugins.editable-table.errors.data_errors.data")

    headers:
      - value: text
        width: 150px

      - value: select
        type: select
        width: 150px
        options:
          - value: option_1
            text: опция 1
          - value: option_2
            text: опция 2
          - value: option_3
            text: опция 3

      - value: multiple-select
        type: multiple-select
        width: 150px
        options:
          - value: option_1
            text: опция 1
          - value: option_2
            text: опция 2
          - value: option_3
            text: опция 3

    source: >
      ({ "body": body })
```

В результате, вывод документа будет иметь вид:

![](@document/archtool.plugins.editable-table.errors.data_errors.table.step_2)
