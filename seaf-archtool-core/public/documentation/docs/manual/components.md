# Компоненты (components)
Компоненты являются базовыми сущностями SEAF.ArchTool. На их основе автоматически генерируются диаграммы связей.
Для успешной генерации компоненты содержат необходимые метаданные.

Пример описания компонента в манифесте [манифесте](https://gitverse.ru/seafteam/seaf-archtool-core/content/master/public/documentation/arch/components/front.yaml):
```yaml
components:
  #***********************************************************
  #                       C4Model L1
  #***********************************************************
  archtool.front:             # Идентификатор компонента
    title: SEAF.ArchTool           # Название компонента
    entity: component       # Сущность компонента из PlantUML (https://plantuml.com/ru/deployment-diagram)
    source: ./              # Кастомное поле определенное в forms
    technologies:           # Используемые технологии
      - JavaScript
      - VUEJS3
      - Chrome
      - Firefox
      - Safari
    aspects:                # Аспекты, которе реализует компонент
      - archtool.gitlab.auth
      - archtool.manifest.parsing
      - archtool.contexts
      - archtool.aspects
      - archtool.docs
      - archtool.navigation
      - archtool.dataset
    links:                            # Зависимость компонента от других компонентов
      - id: archtool.gitlab             # Идентификатор компонента
        direction: '<--'              # Напрвлене связи
        title: Манифесты и документы  # Надпись на связи
        contract: archtool.swagger      # Идентификатор документа описывающего контракт (может быть прямой ссылкой, например: http://foo.com)
      - id: archtool.plantuml
        direction: '-->'
        title: PlantUML
      - id: archtool.plantuml
        direction: '<-'
        title: Схема SVG
      - id: archtool.web
        direction: '<--'
        title: Манифесты и документы
```

![Карточка компонента](@component/archtool.front)
