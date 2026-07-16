# Настройка

Рассмотрим основные параметры и настройки.

# Сертификаты

Обязательные параметры.

Для корректной работы требуется установить сертификаты Минцифры и указать путь к ним в параметрах:

- `VUE_APP_GIGACHAT_CA_BUNDLE_FILE`
- `VUE_APP_GIGACHAT_CERT_FILE`
- `VUE_APP_GIGACHAT_KEY_FILE`

Информация о сертификатах содержится в статье: [Использование сертификатов Минцифры в GigaChat](https://developers.sber.ru/docs/ru/gigachat/certificates)

# `VUE_APP_GIGACHAT_BASE_URL`

Обязательный параметр.

URL к API GigaChat.

# `VUE_APP_GIGACHAT_AUTH_URL`

Обязательный параметр для режима Банк, указывается URL IDP банка.

URL для получения токена доступа для авторизации запросов к API.

# `VUE_APP_GIGACHAT_CREDENTIAL`

Обязательный параметр.

Токен доступа для авторизации запросов к API.

Токен можно получить в [личном кабинете GigaChat](https://developers.sber.ru/).

# `VUE_APP_GIGACHAT_SCOPE`

Обязательный параметр.

Версия API.

Возможные значения перечислены в [документации](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token).

# `VUE_APP_GIGACHAT_DEFAULT_MODEL`

Используемая по умолчанию модель.

# `VUE_APP_GIGACHAT_TIMEOUT`

`timeout` соединения - максимальное время поддержания соединения в `ms`.
