# ⚠️ Важные особенности ⚠️

- После сохранения комментарии в файле будут утеряны
- На данный момент возможно указать только относительный путь для сохранения. Он рассчитывается от файла, где описана таблица
- При сохранении без использования форматирования `format` данные из таблицы вмерживаются в данные файла, что может сломать структуру

# Подготовим данные для новой таблицы

```yaml
archtool.plugins.editable-table.editing.data:
  row_1:
    name: Иванов Иван Иванович
    color: white
  row_2:
    name: Петров Петр Петрович
    color: blue
  row_3:
    name: Семенов Семен Семенович
    color:
```

# Создадим новую таблицу и наполним ее данными

```yaml
docs:
  archtool.plugins.editable-table.editing.table_1:
    type: editable-table

    origin:
      body: >
        ($."archtool.plugins.editable-table.editing.data")

    headers:
      - value: name
        width: 200px
      - value: color
        type: select
        options:
          - value: red
          - value: blue
          - value: white
        width: 100px
    source: >
      (
          { "body": body }
      )
```

![](@document/archtool.plugins.editable-table.editing.table_1)

# Начало редактирования

Редактируемые значения в таблице устанавливаются путем установки в `headers`:

- флага `editable` - указание, что значение редактируемое (значение по умолчанию - `false`)
- опций `save`/`path` - путь к файлу

Укажем флаг и путь для сохранения файла (пока укажем путь к файлу не подключенному к озеру)

```yaml
  archtool.plugins.editable-table.editing.table_2:
    type: editable-table
    new_row_allowed: false # Отключим создание новых строк
    origin:
      body: >
        ($."archtool.plugins.editable-table.editing.data")

    headers:
      - value: name
        width: 200px
      - value: color
        type: select
        options:
          - value: red
          - value: blue
          - value: white
        width: 100px
        editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
        save:
          path: data/test_data.yaml
    source: >
      (
          { "body": body }
      )
```

![](@document/archtool.plugins.editable-table.editing.table_2)

Обратите внимание на текущее поведение:

- при сохранении данные таблицы вносятся поверх данных файла, т.о. часть данных может быть утеряна
- после сохранения, данные в таблице возвращаются к исходному виду, т.к. не подключены к озеру
- в сохраняемый файл попадают данные только из одной колонки

Давайте исправим это поведение.

# Редактируем данные в озере

Для решения части проблем воспользуется свойством `format`.
Это JSONata выражение позволяет получить данные из файла и таблицы, произвольным образом их преобразовать и сохранить результат.

В JSONata выражении доступны:

- Данные из файла как параметр (origin) "file" (зарезервированное имя)
- Слайс данных (данные из колонок сохраняемые по одному пути) из таблицы как параметр (origin) "table" (зарезервированное имя)
- Данные из всей таблицы как параметр (origin) "full_table" (зарезервированное имя)
- Все прочие описанные `origin`

Опишем `format`:

```yaml
format: >
  (
      $key := $keys(file)[0];
      { $key: table }
  )
```

Заменим путь сохранения на подключенный к озеру файл с `path: data/test_data.yaml` на `path: data/data.yaml`.
Для приведения данных в файле к одному типу, дополнительно будем сохранять первую колонку, но без возможности редактирования.

```yaml
headers:
  - value: name
    width: 200px
    save:
      path: data/data.yaml
  - value: color
    type: select
    options:
      - value: red
      - value: blue
      - value: white
    width: 100px
    editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
    save:
      path: data/data.yaml
```

Финальный вид:

```yaml
  archtool.plugins.editable-table.editing.table_3:
    type: editable-table
    new_row_allowed: false # Отключим создание новых строк
    origin:
      body: >
        ($."archtool.plugins.editable-table.editing.data")

    format: >
      (
          $key := $keys(file)[0];
          { $key: table }
      )

    headers:
      - value: name
        width: 200px
        save:
          path: data/data.yaml
      - value: color
        type: select
        options:
          - value: red
          - value: blue
          - value: white
        width: 100px
        editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
        save:
          path: data/data.yaml
    source: >
      (
          { "body": body }
      )

```

![](@document/archtool.plugins.editable-table.editing.table_3)

Как можно заметить, данные в файле после сохранения, если значение в таблице не было заполнено, имеют вид:

```yaml
archtool.plugins.editable-table.editing.data":
  row_1:
    name: Иванов Иван Иванович
    color:
```

# Поменяем пустые строки в сохраняемом файле на другое значение

Для этого воспользуемся свойством `yaml` / `null_replace_string`. Оно позволяет заменить пустые значения при сохранении.

```yaml
  archtool.plugins.editable-table.editing.table_4:
    type: editable-table
    new_row_allowed: false # Отключим создание новых строк
    yaml:
      null_replace_string: "не заполнено"

    origin:
      body: >
        ($."archtool.plugins.editable-table.editing.data")

    format: >
      (
          $key := $keys(file)[0];
          { $key: table }
      )

    headers:
      - value: name
        width: 200px
        save:
          path: data/data.yaml
      - value: color
        type: select
        options:
          - value: red
          - value: blue
          - value: white
        width: 100px
        editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
        save:
          path: data/data.yaml
    source: >
      (
          { "body": body }
      )
```

![](@document/archtool.plugins.editable-table.editing.table_4)
