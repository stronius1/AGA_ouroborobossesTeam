# Задача

## Составить таблицу для данных

```yaml
archtool.plugins.editable-table.styles.examples.base_example.data:
  row_1:
    name: Иванов Иван Иванович
    gender: male
    age: 36
    colors: ["orange"]
  row_2:
    name: Петров Петр Петрович
    age:
    colors: ["green", "red", "teal"]
  row_3:
    name: Семенова Ирина Вячеславовна
    gender: female
    age: 10
    colors:
  row_4:
    name: Семенов Семен Семенович
    gender: male
    age: 25
    colors: ["green"]
  row_5:
    name: Александрова Алиса Ивановна
    gender: female
    age: 36
    colors:
  row_6:
    name: Орлов Дмитрий Сергеевич
    gender: male
    age: 76
    colors: ["teal", "blue"]
```

Таблица должна состоять из 4 колонок:

- `name` - text
- `gender` - select
- `age` - text
- `colors` - multiple-select

## Стилизовать таблицу

1. `name` - если строка с именем содержит подстроку "Иван" - выделить текст жирным
2. `age`

- если возраст < 18 - сделать фон желтым
- если возраст > 18 и < 60 - сделать фон зеленым
- иначе сделать фон синим
- сделать цвет текста белым для всех

3. `colors` - каждое значение окрасить соответствующим цветом

# Решение

## Подготовим таблицу

```yaml
archtool.plugins.editable-table.styles.examples.base_example.table.step_1:
  type: editable-table
  origin:
    body: >
      ($."archtool.plugins.editable-table.styles.examples.base_example.data")
  headers:
    - value: name
    - value: gender
      type: select
      options:
        - value: male
          text: муж
        - value: female
          text: жен
    - value: age
    - value: colors
      type: multiple-select
      options:
        - value: blue
          text: Синий
        - value: green
          text: Зеленый
        - value: red
          text: Красный
        - value: teal
          text: Бирюзовый
        - value: orange
          text: Оранжевый
        - value: yellow
          text: Желтый
  source: >
    (
        { "body": body }
    )
```

![](@document/archtool.plugins.editable-table.styles.examples.base_example.table.step_1)

## Добавим стили

Для колонки `name`

```yaml
- value: name
  styles:
    bold-font-for-ivan:
      fontWeight: bold
      conditions:
        - condition_type: includes
          value: Иван
```

Для колонки `age`

```yaml
- value: age
  styles:
    default:
      backgroundColor: blue
      color: white
    less-then-60:
      backgroundColor: green
      conditions:
        - condition_type: "<"
          value: 60
    less-then-18:
      backgroundColor: yellow
      conditions:
        - condition_type: "<"
          value: 18
```

Для колонки `colors`

```yaml
- value: colors
  type: multiple-select
  options:
    - value: blue
      text: Синий
    - value: green
      text: Зеленый
    - value: red
      text: Красный
    - value: teal
      text: Бирюзовый
    - value: orange
      text: Оранжевый
    - value: yellow
      text: Желтый
  styles:
    blue:
      backgroundColor: blue
      conditions:
        - condition_type: equal
          value: blue
    green:
      backgroundColor: green
      conditions:
        - condition_type: equal
          value: green
    red:
      backgroundColor: red
      conditions:
        - condition_type: equal
          value: red
    teal:
      backgroundColor: teal
      conditions:
        - condition_type: equal
          value: teal
    orange:
      backgroundColor: orange
      conditions:
        - condition_type: equal
          value: orange
    yellow:
      backgroundColor: yellow
      conditions:
        - condition_type: equal
          value: yellow
```

## Результат

```yaml
archtool.plugins.editable-table.styles.examples.base_example.table.step_2:
  type: editable-table
  origin:
    body: >
      ($."archtool.plugins.editable-table.styles.examples.base_example.data")
  headers:
    - value: name
      styles:
        bold-font-for-ivan:
          fontWeight: bold
          conditions:
            - condition_type: includes
              value: Иван

    - value: gender
      type: select
      options:
        - value: male
          text: муж
        - value: female
          text: жен
    - value: age
      styles:
        default:
          backgroundColor: blue
          color: white
        less-then-60:
          backgroundColor: green
          conditions:
            - condition_type: "<"
              value: 60
        less-then-18:
          backgroundColor: yellow
          conditions:
            - condition_type: "<"
              value: 18
    - value: colors
      type: multiple-select
      options:
        - value: blue
          text: Синий
        - value: green
          text: Зеленый
        - value: red
          text: Красный
        - value: teal
          text: Бирюзовый
        - value: orange
          text: Оранжевый
        - value: yellow
          text: Желтый
      styles:
        blue:
          backgroundColor: blue
          conditions:
            - condition_type: equal
              value: blue
        green:
          backgroundColor: green
          conditions:
            - condition_type: equal
              value: green
        red:
          backgroundColor: red
          conditions:
            - condition_type: equal
              value: red
        teal:
          backgroundColor: teal
          conditions:
            - condition_type: equal
              value: teal
        orange:
          backgroundColor: orange
          conditions:
            - condition_type: equal
              value: orange
        yellow:
          backgroundColor: yellow
          conditions:
            - condition_type: equal
              value: yellow
  source: >
    (
        { "body": body }
    )
```

![](@document/archtool.plugins.editable-table.styles.examples.base_example.table.step_2)
