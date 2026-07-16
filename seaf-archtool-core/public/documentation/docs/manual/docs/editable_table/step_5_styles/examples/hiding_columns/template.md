# Скрытие колонок

Флаг для заголовка `display` позволяет скрыть колонку.
Колонки не доступны в интерфейсе, но прочий функционал для скрытой ячейки сохраняется.
Т.о. мы можем сохранять скрытые ячейки, использовать ячейки в заголовках `fn`, форматировании и пр.

Подготовим таблицу и скроем несколько колонок.

```yaml
archtool.plugins.editable-table.styles.examples.hiding_columns.table.step_1:
  type: editable-table
  origin:
    body: >
      ($."archtool.plugins.editable-table.styles.examples.hiding_columns.data")
  headers:
    - value: column_1
      width: 100px
    - value: column_2
      width: 100px
    - value: column_3
      width: 100px
    - value: column_4
      width: 100px
  source: >
    (
        { "body": body }
    )
```

![](@document/archtool.plugins.editable-table.styles.examples.hiding_columns.table.step_1)


Добавим значение `display: false` для заголовков column_2 и column_4.

```yaml
archtool.plugins.editable-table.styles.examples.hiding_columns.table.step_2:
  type: editable-table
  origin:
    body: >
      ($."archtool.plugins.editable-table.styles.examples.hiding_columns.data")
  headers:
    - value: column_1
      width: 150px
    - value: column_2
      width: 150px
      display: false
    - value: column_3
      width: 150px
    - value: column_4
      width: 150px
      display: false
  source: >
    (
        { "body": body }
    )
```

![](@document/archtool.plugins.editable-table.styles.examples.hiding_columns.table.step_2)

