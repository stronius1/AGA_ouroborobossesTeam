# `AiGenA` - агент

# Описание

Агент позволяет взаимодействовать с API AiGenA. Основной особенностью является, что агент знаком со стандартами ДЗО.

# ⚠️ Доступность ⚠️

Агент доступен в:

- `backend`-mode, в сети Банка

# Знакомство

Агент не требует описания дополнительных свойств. Достаточно указать только тип агента

```yaml
docs:
  archtool.plugins.gigachat.agents:
    type: ai-chat
    scenarios:
      consultant:
        title: AiGenA
        type: aigena
```
