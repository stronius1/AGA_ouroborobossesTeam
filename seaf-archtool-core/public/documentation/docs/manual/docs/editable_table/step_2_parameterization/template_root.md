Разберем пример использования параметризации.

В этом примере мы будем передавать в таблицу параметр `pets` с двумя возможными значениями `cats` и `dogs`. В зависимости от переданных значений будем отображать различные заголовки в таблице

В этот раз будем использовать данные из архитектурного озера.

# Подготовим и подключим данные в озеро для текущего примера

```yaml
archtool.plugins.editable-table.parameterization.data:
  pets:
    cats:
      - name: Барсик
        color: серый
        vaccinated: true
      - name: Рыжик
        color: рыжий
        vaccinated: false
      - name: Мурка
        color: черно-белый
        vaccinated: true
      - name: Черныш
        color: черный
        vaccinated: true
    dogs:
      - name: Барон
        color: черный
        vaccinated: true
      - name: Рекс
        color: серый
        vaccinated: true
```

# Сформируем меню и презентацию

```yaml
entities:
  systems:
    menu: >
      (
        $pets := $keys($."archtool.plugins.editable-table.parameterization.data".pets);
        $start_location := "Документы/SEAF.ArchTool/Руководство/Документы/Редактируемая таблица/2. Параметризация/";
      
        $map($pets, function($v, $i, $a) {(
            $name := $v = "cats" ? "2. 1. Параметр - 1 (Кошки)" : "2. 2. Параметр - 2 (Собаки)";
            {
                "location": $start_location & $name,
                "link": "/entities/systems/archtool.plugins.editable-table.parameterization.table?id=" & $v
            }
          )})
      )

    presentations:
      archtool.plugins.editable-table.parameterization.table:
        title: Таблица
        type: markdown
        template: template_table.md
        source: >
          (
              $id := $params.id;
              { "pet": $id }
          )
```

# Опишем таблицу

```yaml
docs:
  archtool.plugins.editable-table.parameterization.table:
    type: editable-table
    origin:
      body: >
        (
            $pet_type := $params.pet;
            $pets := $lookup($."archtool.plugins.editable-table.parameterization.data".pets, $pet_type);

            $table_data := $reduce($pets, function($acc, $v, $i){(
                $row_id := "row_" & $i;
                $row := {$row_id: $v};
                $merge([$acc, $row])
            )}, {})
        )
      headers: >
        (
          /* из переданных параметров получим значение "cats" или "dogs"  */
          $pet_type := $params.pet;

          /* добавим заголовок для обоих кейсов  */
          $default_header := { "value": "name", "text": "кличка" };

          /* добавим заголовок по условию  */
          $conditional_header := $pet_type = "cats"
            ? { "value": "color", "text": "цвет" }
            : { "value": "vaccinated", "type": "checkbox", "text": "вакцинирован" };

          $map([$default_header, $conditional_header], function($v){(
            $merge([$v, {"width": "150px"}])
          )})
        )
    source: >
      (
          { "body": body, "headers": headers }
      )
```

В текущем примере мы подготовили для таблицы различные заголовки в зависимости от переданных параметров.
В случае передачи параметра:

- [`cats`](/entities/systems/archtool.plugins.editable-table.parameterization.table?id=cats) - показываем цвет питомца
- [`dogs`](/entities/systems/archtool.plugins.editable-table.parameterization.table?id=dogs) - показываем привит ли питомец
