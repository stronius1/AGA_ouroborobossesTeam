import { Function as GigaChatToolSchema } from 'gigachat/interfaces';

const BASE_SCHEMA = {
  description: `
    Осуществляет сохранение данных.

    Ожидает 2 аргумента:
      1.  [path] - относительный путь сохранения данных.
      2.  [data] - данные для сохранения.

    Аргументы для вызова ДОЛЖЫ БЫТЬ ЗАДАНЫ ЯВНО:
      - Переданы пользователем.
      - Являться рузультатом выполнения другого инструмента (тула), если это было указано пользователем или системным промптом. 
        В этом случае НЕЛЬЗЯ меняться структуру, формат или вложенность данных. 
  `,
  name: 'put_content',
  parameters: {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description:
          'Директория сохранения файла с указанием расширения файла. Поддерживаемые расшрения - yaml, json'
      },
      data: {
        type: 'string',
        description: 'Сохраняемые данные'
      }
    },
    required: ['path', 'data']
  },
  return_parameters: {
    type: 'object',
    properties: {
      success: {
        type: 'boolean',
        description: 'Флаг указывающий на успешное сохранение'
      },
      errorMessage: {
        type: 'string',
        description:
          'Возвращается при возникновении ошибок при выполнении. Содержит описание возникшей ошибок при сохранении'
      }
    },
    required: ['success']
  },
  few_shot_examples: [
    {
      request:
        'Сформируй путь для сохранения и данные используя соответсвующие инстурменты (тулы) и выполни сохранение используя инстурмент "put_content"',
      params: {
        path: 'file.yaml',
        data: '[\n  {\n    "city": "Mosscow"\n  },\n  {\n    "city": "Omsk"\n  }\n]'
      }
    },
    {
      request: 'Сохрани объект `{"hello": "world"}` в файл `file.yaml`',
      params: {
        path: 'file.yaml',
        data: '{ "hello": "world" }'
      }
    }
  ]
};

const BACKEND_SCHEMA = {
  description: `
    Осуществляет сохранение данных.

    Ожидает 2 аргумента:
      1.  [path] - путь сохранения данных.
          Путь для сохраняемого файла может быть 2-х видов:
            - Относительный (относительно документа где описан данный чат).
              Пример - 'path/to/file.yaml'.

            - Глобальный (указывается обязательный префикс '@' и ссылка на файл в репозитории).
              Пример глобального пути - '@bitbucket:MY_PROJECT:my_repository:my_branch@path/to/file.yaml'.
              Описание пути: '@bitbucket:{ИДЕНТИФИКАТОР ПРОЕКТА}:{репозиторий}:{ветка}@{путь до файла с указанием расширения файла}'

      2.  [data] - данные для сохранения.

    Аргументы для вызова ДОЛЖЫ БЫТЬ ЗАДАНЫ ЯВНО:
      - Переданы пользователем.
      - Являться рузультатом выполнения другого инструмента (тула), если это было указано пользователем или системным промптом.
        В этом случае НЕЛЬЗЯ меняться структуру, формат или вложенность данных.
  `,
  few_shot_examples: [
    ...BASE_SCHEMA.few_shot_examples,

    {
      request:
        'Сохрани объект `{"hello": "world"}` в файл \'file.yaml\' в bitbucket в репозиторий \'my_repository\' проекта \'PROJECT\' в ветке \'master\', файл должен находится в директории \'data\'',
      params: {
        path: '@bitbucket:PROJECT:my_repository:master@data/file.yaml',
        content: '{ "hello": "world" }'
      }
    },

    {
      request:
        'Сохрани yaml - контент \'id_1: row_1\nid_2: row_2\' по данному пути \'bitbucket:PROJECT:my_data:master@data/file.yaml\'',
      params: {
        path: '@bitbucket:PROJECT:my_data:master@data/file.yaml',
        content: 'id_1: row_1\nid_2: row_2'
      }
    }
  ]
};

export const putContentPluginSchema: GigaChatToolSchema = BASE_SCHEMA;

export const putContentBackendSchema: GigaChatToolSchema = {
  ...BASE_SCHEMA,
  ...BACKEND_SCHEMA
};
