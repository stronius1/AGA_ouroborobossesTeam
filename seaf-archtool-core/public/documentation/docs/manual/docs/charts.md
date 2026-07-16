# Диаграммы

Для представления диаграмм используется библиотека [chart.js v3](https://www.chartjs.org/)
в обёртке [vue-chartjs v4](https://vue-chartjs.org/) 

Большинство настроек диаграмм передаётся в библиотеку без изменений, 
поэтому для глубокой настройки диаграммы необходимо обращаться к документации библиотек соответствующих версий (для Vue 3).

## Общий подход для настройки диаграммы

```yaml
...
  archtool.charts.examples.common:
    description: Общий подход настройки диаграммы
    author: V.Markin
    # тип диаграммы
    type: chart-radar
    labels:
      - доступность
      - производительность
      - надежность
    # размер диаграммы
    size: 600
    # настройки диаграммы. см. chart.js
    options:
      elements:
        line:
          borderWidth: 7
    source:
      # Метки (даже их часть) можно получать из source
      labels:
        - сопровождаемость
        - обслуживаемость
        - безопасность
      # Настройки (даже их часть) можно получать из source
      options:
        scales:
          r:
            min: 0
            max: 150
      # массив датасетов для заполнения диаграмм
      datasets:
        - label: Система 1
          # если поле заполнено, то применяются настройки представления датасета по-умолчанию,
          # но их можно переопределить. Детализацию по свойствам см. chart.js
          color: rgb(179,181,198)
          # переопределяем цвет точек
          pointBackgroundColor: green
          # данные диаграммы
          data:
            - 65
            - 59
            - 90
            - 81
            - 56
            - 55
        - label: Система 2
          # color не определён, устанавливаем представление датасета вручную
          backgroundColor: rgba(255,99,132,0.2)
          borderColor: rgba(255,99,132,1)
          pointBackgroundColor: rgba(255,99,132,1)
          pointBorderColor: '#fff'
          pointHoverBackgroundColor: '#fff'
          pointHoverBorderColor: rgba(255,99,132,1),
          fill: false,
          data:
            - 28
            - 48
            - 40
            - 19
            - 96
            - 27
...
```

![Общий подход настройки диаграммы на примере Радара](@document/archtool.charts.examples.common)


## Радар
```yaml
...
  archtool.charts.examples.radar:
    description: Пример использования диаграммы Радар
    author: V.Markin
    type: chart-radar
    size: 400
    origin: archtool.charts.examples.radar
    source: ($)
...
datasets:
  archtool.charts.examples.radar:
    source: >
      (
        {
          'size': 600,
          'labels': ['доступность', 'производительность', 'надежность', 'сопровождаемость', 'обслуживаемость', 'безопасность'],
          'datasets': [
            {
                "label": "Система 3",
                "color": "magenta",
                "data": [10, 20, 30, 40, 50, 60]
            },
            {
                "label": "Система 4",
                "color": "green",
                "data": [95, 85, 75, 65, 55, 45]            
            }
          ]
        }
      )
...
```

![Радар](@document/archtool.charts.examples.radar)

## Столбиковая диаграмма
```yaml
...
  archtool.charts.examples.bar:
    description: Пример использования Столбиковой диаграммы
    author: V.Markin
    type: chart-bar
    labels:
      - январь
      - февраль
      - март
      - апрель
      - май
      - июнь
      - июль
      - август
      - сентябрь
      - октябрь
      - ноябрь
      - декабрь
    height: 800
    origin: archtool.charts.examples.bar
    source: ($)
...
datasets:
  archtool.charts.examples.bar:
    source: >
      (
        {
          'datasets': [
            {
              "label": "2022",
              "backgroundColor": "lightblue",
              "data": [30, 10, 2, 29, 50, 30, 29, 70, 30, 20, 42, 11]
            },
            {
              "label": "2023",
              "color": "green",
              "data": [40, 20, 12, 39, 10, 40, 39, 80, 40, 20, 12, 11]
            }
          ]
        }
      )
...
```

![Столбиковая диаграмма](@document/archtool.charts.examples.bar)

## Пузырьковая диаграмма

```yaml
...
    archtool.charts.examples.bubble:
      description: Пример использования Пузырьковой диаграммы
      author: V.Markin
      type: chart-bubble
      origin: archtool.charts.examples.bubble
      source: ($)
...
datasets:
  archtool.charts.examples.bubble:
    source: >
      (
        {
          'datasets': [
            {
              'label': 'Набор 1',
              'backgroundColor': '#f87979',
              'data': [ {'x':20,'y':25,'r':5}, {'x':40,'y':10,'r':10}, {'x':30,'y':22,'r':30} ]
            },
            {
              'label': 'Набор 2',
              'backgroundColor': '#7C8CF8',
              'data': [ {'x':10,'y':30,'r':15}, {'x':20,'y':20,'r':10}, {'x':15,'y':8,'r':30} ]
            }        
          ]
        }
      )
...
```

![Пузырьковая диаграмма](@document/archtool.charts.examples.bubble)

## Кольцевая диаграмма

```yaml
...
    archtool.charts.examples.doughnut:
      description: Пример использования Кольцевой диаграммы
      author: V.Markin
      type: chart-doughnut
      labels:
        - VueJs
        - EmberJs
        - ReactJs
        - AngularJs
      source: >
        (
          {
            'datasets': [
              {
                'color': ['#41B883', '#E46651', '#00D8FF', '#DD1B16'],
                'data': [40, 20, 80, 10]
              }
            ]
          }
        )
...
```

![Кольцевая диаграмма](@document/archtool.charts.examples.doughnut)

## Линейная диаграмма

```yaml
...
  archtool.charts.examples.line:
    description: Пример использования Линейной диаграммы
    author: V.Markin
    type: chart-line
    labels:
      - январь
      - февраль
      - март
      - апрель
      - май
      - июнь
      - июль
      - август
      - сентябрь
      - октябрь
      - ноябрь
      - декабрь
    source: >
      (
        {
          'datasets': [
            {
              "label": "2022",
              "color": "lightblue",
              "data": [30, 10, 2, 29, 50, 30, 29, 70, 30, 20, 42, 11]
            },
            {
              "label": "2023",
              "color": "green",
              "data": [40, 20, 12, 39, 10, 40, 39, 80, 40, 20, 12, 11]
            }
          ]
        }
      )
...
```

![Линейная диаграмма](@document/archtool.charts.examples.line)

## Круговая диаграмма

```yaml
...
    archtool.charts.examples.pie:
      description: Пример использования Круговой диаграммы
      author: V.Markin
      type: chart-pie
      source: >
        (
          {
            'labels': ['VueJs', 'EmberJs', 'ReactJs', 'AngularJs'],
            'datasets': [
              {
                'color': ['#41B883', '#E46651', '#00D8FF', '#DD1B16'],
                'data': [40, 20, 80, 10]
              }
            ]
          }
        )
...
```

![Круговая диаграмма](@document/archtool.charts.examples.pie)

## Полярная диаграмма

```yaml
...
    archtool.charts.examples.polararea:
      description: Пример использования Полярной диаграммы
      author: V.Markin
      type: chart-polararea
      labels:
        - доступность
        - производительность
        - надежность
        - сопровождаемость
        - обслуживаемость
        - безопасность
      origin: archtool.charts.examples.polararea
      source: ($)
...
datasets:
  archtool.charts.examples.polararea:
    source: >
      (
        {
          'datasets': [
            {
              "label": "Система 3",
              "color": "magenta",
              "data": [10, 20, 30, 40, 50, 60]
            },
            {
              "label": "Система 4",
              "color": "green",
              "data": [95, 85, 75, 65, 55, 45]
            }
          ]
        }
      )
...
```

![Полярная диаграмма](@document/archtool.charts.examples.polararea)

## Точечная диаграмма

```yaml
...
    archtool.charts.examples.scatter:
      description: Пример использования Точечной диаграммы
      author: V.Markin
      type: chart-scatter
      origin: archtool.charts.examples.scatter
      source: ($)
...
datasets:
  archtool.charts.examples.scatter:
    source: >
      (
        {
          'datasets': [
            {
              'label': 'Набор данных 1',
              'color': '#f87979',
              'data': [ {'x':-2,'y':4}, {'x':-1,'y':1}, {'x':0,'y':0}, {'x':1,'y':1}, {'x':2,'y':4} ]
            },
            {
              'label': 'Набор данных 2',
              'color': '#7acbf9',
              'data': [ {'x':-2,'y':-4}, {'x':-1,'y':-1}, {'x':0,'y':1}, {'x':1,'y':-1}, {'x':2,'y':-4} ]
            }
          ]
        }
      )
...
```

![Точечная диаграмма](@document/archtool.charts.examples.scatter)
