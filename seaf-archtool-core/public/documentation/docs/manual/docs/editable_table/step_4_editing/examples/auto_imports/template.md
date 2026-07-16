# Обновление импортов при сохранении

# ⚠️ Важные особенности ⚠️
Функционал доступен только в режиме плагина

## Описание

При сохранении часть файлов или все файлы могут быть не подключены (импортированы) к озеру, но могут быть использованы в таблице, в следствии чего, после сохранения, таблица снова окажется пустой.
Можно использовать опцию `update_index_file` для подключения файлов к манифесту. В качестве значения указывается наименование импорт-файлов в вашем проекте (обычно используется `root.yaml`).

Опишем нашу таблицу:

```yaml
archtool.plugins.editable-table.editing.auto_imports.table:
  type: editable-table
  new_row_allowed: false # Отключим создание новых строк
  update_index_file: root.yaml
  format: >
    (
        $data_id := "archtool.plugins.editable-table.editing.auto_imports.data";
        { $data_id: table }
    )
  origin:
    options: >
      ([
          {"value": "green", "text": "Зеленый"},
          {"value": "blue", "text": "Синий"},
          {"value": "white", "text": "Белый"},
          {"value": "black", "text": "Черный"}
      ])
    body: >
      ($."archtool.plugins.editable-table.editing.auto_imports.data")
  headers:
    - value: column_1
      width: 150px
      type: select
      options: >
        (options)
      editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
      save:
        path: ./data/data_column_1.yaml
    - value: column_2
      width: 150px
      type: select
      options: >
        (options)
      editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
      save:
        path: ./data/data_column_2.yaml
    - value: column_3
      width: 150px
      type: select
      options: >
        (options)
      editable: false # Отключено (ссылка на репозиторий на главной странице плагина)
      save:
        path: ./data/column_3/data_column_3.yaml
  source: >
    (
        { "body": body }
    )
```

Как мы видим, в таблице описаны следующие пути сохранения:
- колонка `column_1` - `./data/data_column_1.yaml`
- колонка `column_2` - `./data/data_column_2.yaml`
- колонка `column_3` - `./data/column_3/data_column_3.yaml`

Файл для колонки `column_1` уже существует и подключен к озеру.

Для таблицы добавлена опция `update_index_file: root.yaml`, что позволит импортировать файлы после сохранения.

## Рассмотрим алгоритм сохранения подробно

### Заголовок column_1 (`path: ./data/data_column_1.yaml`)

- `plugins/editable_table/step_4_editing/examples/auto_imports/data/data_column_1.yaml` - Файл подключен к манифесту.
- - Записываем файл с данными таблицы

### Заголовок column_2 (`path: ./data/data_column_2.yaml`)

- `plugins/editable_table/step_4_editing/examples/auto_imports/data/data_column_2.yaml` - Файл не подключен.
- -  Записываем файл с данными таблицы и подключаем к импорт файлу новый импорт `data_column_2.yaml`.
- `plugins/editable_table/step_4_editing/examples/auto_imports/data/root.yaml` - Файл подключен к манифесту.

В root.yaml будет добавлен новый импорт:
```yaml
imports:
  - ...
  - data_column_2.yaml
```

### Заголовок column_3 (`path: ./data/column_3/data_column_3.yaml`)

- `plugins/editable_table/step_4_editing/examples/auto_imports/data/column_3/data_column_3.yaml` - Файл не подключен.
- - Записываем файл с данными таблицы и подключаем к импорт файлу новый импорт `data_column_3.yaml`.
- `plugins/editable_table/step_4_editing/examples/auto_imports/data/column_3/root.yaml` - Файл не подключен.
- - Записываем файл и подключаем к импорт-файлу новый импорт `data_column_3.yaml`. Переходим в директорию ниже.
- `plugins/editable_table/step_4_editing/examples/auto_imports/data/root.yaml` - Файл подключен к манифесту.

Таким образом, мы:
1. Записали данные таблицы в файл `plugins/editable_table/step_4_editing/examples/auto_imports/data/column_3/data_column_3.yaml`.
2. Записали импорт-файл `plugins/editable_table/step_4_editing/examples/auto_imports/data/column_3/root.yaml`:

```yaml
imports:
  - data_column_3.yaml
```

3. Добавили импорт в уже подлюченному к манифесту импорт-файле в директории ниже `plugins/editable_table/step_4_editing/examples/auto_imports/data/root.yaml`:
```yaml
imports:
  - ...
  - column_3/root.yaml
```

![](@document/archtool.plugins.editable-table.editing.auto_imports.table)
