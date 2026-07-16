# SEAF2Drawio
Плагин для конвертации объектов метамодели SEAF в объекты DrawIO для формирования диаграммы технической архитектуры.
## Описание документа
``` yaml
  something.seafdrawio_new_combined:
    location: Test/seaf2drawio/New combined
    description: seaf2drawio with templates
    type: seaf2drawio
    origin:
      diff: something.seaf2drawio_example.diff
      dataset: something.seaf2drawio_example.combined
      templates: something.seaf2drawio_example.templates
    source: >
      (
        {
          "title": "Название документа",
          "dataset": dataset,
          "templates": templates,
          "diff": diff
        }
      )
```
В качестве источника документ принимает объект со следующими параметрами:
- **title** Необязательный, задаёт заголовок документа.
- **dataset** Обязательный, содержит описание объектов архитектуры.
- **templates** Необязательный, содержит пользовательские шаблоны для объектов или переопределения встроенных шаблонов.
- **diff** Необязательный, содержит трансформации для отображаемой диаграммы.
- **layout_settings** Необязательный, содержит настройки для алгоритма распределения сетевых сервисов по группам.
## Описание пользовательских шаблонов
Описание шаблона элемента Draw.io может содержать следующие атрибуты.
| Атрибут            | Описание                                                                                                             |
|--------------------|----------------------------------------------------------------------------------------------------------------------|
| **xml**            | Шаблон XML описания объекта (может состоять из одного или группы объектов. Группа объектов заключается в тэг <root>) |
| **schema**         | Ссылка на схему объекта SEAF                                                                                         |
| **parent_id**      | Ключ объекта SEAF содержащий ID родительского объекта                                                                |
| **parent_key**     | Ключ родительского объекта SEAF необходимый для выбора отображаемых объектов                                         |
| **type**           | "имя ключа:ожидаемое значение" Тип объекта для персонализации визуального объекта                                    |
| **algo**           | Алгоритм позиционирования однотипных объектов (X+, X-, Y+, Y-) по строкам или столбцам                               |
| **offset**         | Смещение однотипных объектов друг относительно друга                                                                 |
| **deep**           | Количество однотипных объектов в строке или столбце до перехода на новую строку/столбец                              |
| **x,y**            | Позиция левого верхнего угла объекта                                                                                 |
| **w,h**            | Ширина/Высота объекта                                                                                                |
| **ext_page**       | Шаблон создания дополнительной диаграммы для детальной схемы офис/ЦОД                                                |
| **targets**        | Ключ объекта SEAF содержащий перечень связываемых линками объектов                                                   |
----------------------------------------------------------------------------------------------------------------------------------------------
Переменные в одинарных скобках {} подменяются данными их модели SEAF, переменные в двойных скобках {{}} определяют параметры позиционирования, размеры и подпись объектов.

``` yaml
datasets:
  something.seaf2drawio_example.templates
    source:
      office:
        router:
          xml: > 
            <object label="{{label}}" id="{{id}}">
              <mxCell style="shape=mxgraph.cisco.routers.router;sketch=0;html=1;fillColor=aqua;verticalLabelPosition=bottom;" parent="{segment}" vertex="1">
                <mxGeometry x="{{x_pos}}" y="{{y_pos}}" width="{{width}}" height="{{height}}" as="geometry" />
              </mxCell>
            </object>
          schema: seaf.ta.components.network
          parent_id: segment
          type: type:Маршрутизатор
          algo: Y+
          deep: 7
          offset: 30
          x: 20
          y: 135
          w: 40
          h: 30
      dc:
        lan:
          xml: >
            <object label="&lt;div &gt;&lt;p style=&quot;align:center;font-family:Arial;font-size:10px;valign:middle&quot;&gt;&lt;font style=&quot;font-size:14px;&quot;&gt;&lt;b&gt;{title}&lt;/b&gt;&lt;/font&gt;&lt;font&gt;{ipnetwork}&lt;/font&gt;&lt;/p&gt;&lt;/div&gt;" id="{id}">
              <mxCell style="rotation=-90;fillColor=salmon;rounded=1;html=1;whiteSpace=wrap;" vertex="1" parent="{segment}">
                <mxGeometry x="{{x_pos}}" y="{{y_pos}}" width="{{height}}" height="{{width}}" as="geometry" />
              </mxCell>
            </object>
          schema: seaf.ta.services.network
          parent_id: segment
          type: type:LAN
          algo: Y+
          deep: 4
          offset: 60
          x: -10
          y: 140
          w: 30
          h: 220
```
## Трансформации
Изменения, которые пользователь внёс на построенную диаграмму можно сохранить в виде набора трансформаций. Для этого в правом верхнем углу экрана расположена кнопка Export Transformations сохраняющая внесённые на диаграмму изменения в yaml-формате.

Трансформации предназначены для сохранения визуальных изменений (положение объектов, положение стрелок, и т.п.) и не предназначены для изменений иерархии или архитектурных данных (перенос сервисов в другие подсети, изменения описаний и т.п.).

После сохранения файла трансформаций его следует приложить к архитектурным данным, сформировать датасет и записать в параметр diff документа seaf2drawio.

Пример объявления документа:
``` yaml
docs:
  archtool.plugins.example.seaf2drawio.transformations:
    type: seaf2drawio
    location: SEAF.ArchTool/Руководство/Документы/SEAF2Draw.io/Примеры/Трансформации
    origin:
      dataset: archtool.plugins.example.seaf2drawio.data
      diff: archtool.plugins.example.seaf2drawio.diff
    source: >
      (
          {
            "title": "Применение трансформаций",
            "dataset": dataset,
            "diff": diff
          }
      )

datasets:
  archtool.plugins.example.seaf2drawio.diff:
    source: ./diff.yaml

```