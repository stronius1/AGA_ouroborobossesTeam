import { Function as GigaChatToolSchema } from 'gigachat/interfaces';
import { ToolInterface } from '../types/ToolInterface';
import { ToolTypes } from '../types/ToolTypes';
import { ToolConfigType } from '../types/ToolConfigType';
import { DocumentConfigType } from '../types/DocumentConfigType';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { RequestWithBenefits } from '@back/controllers/gigachat';

import YAML from 'yaml';

const logger = getLoggerWithTag('PutContentTool');

const PARSER = {
  json: JSON,
  yaml: YAML
}; 
const VALID_EXTENSIONS = Object.keys(PARSER);

export type PutContentToolCallback = (
  path: string,
  content: string,
  profile: {
    base: string;
  },
  request?: RequestWithBenefits
) => void;

export class PutContentTool implements ToolInterface {
  type: ToolTypes.putContent;
  schema: GigaChatToolSchema;

  private callback: PutContentToolCallback;

  constructor(callback: PutContentToolCallback, schema: GigaChatToolSchema) {
    this.type = ToolTypes.putContent;
    this.schema = schema;
    this.callback = callback;

    logger.debug(
      () => `Put Content tool registered with type: "${ToolTypes.putContent}"`
    );
  }

  async execute(
    args: any,
    toolConfig: ToolConfigType,
    documentConfig: DocumentConfigType,
    sessionId: string,
    request?: RequestWithBenefits
  ) {
    const { path, data } = this.validateGeneratedParams(args);

    try {
      await this.callback(path, data, documentConfig.profile, request);

      return { success: true };
    } catch (err) {
      return { success: false, errorMessage: err.message };
    }
  }

  private validateGeneratedParams(args: any): {
    path: string;
    data: string;
  } {
    if (!(args && typeof args === 'object' && !Array.isArray(args))) {
      throw new Error(
        `Ошибка в инструменте с типом "${this.type}". Сформированн невалидный объект аргументов ("${args}")!`
      );
    }

    const params: Record<string, string> = {};
    for (const key in args) {
      const trimedKey = key.trim(); // llm может сгенерировать ключи с пробелами ({ " path": ... })
      params[trimedKey] = args[key];
    }

    const path = params?.path;
    
    if (!(typeof path === 'string' && path.length > 0)) {
      throw new Error(
        `Ошибка в инструменте с типом "${this.type}". Не задан путь для сохранения ("${path}")!`
      );
    }

    const splitedPath = path.split('.');
    const extension = splitedPath.at(-1);
    const pathWithOutExtension = splitedPath.slice(0, -1).join('.');

    if (pathWithOutExtension.length === 0) {
      throw new Error(
        `Ошибка в инструменте с типом "${this.type}". Не задан путь для сохранения!`
      );
    }

    if (!VALID_EXTENSIONS.includes(extension)) {
      this.generageInvalidFormatError(extension);
    }

    const data = params?.data;

    if (!data) {
      throw new Error(
        `Ошибка в инструменте с типом "${this.type}". Не задан контекнт для сохранения!`
      );
    }

    const validatedData =
      typeof data === 'string'
        ? this.changeDataStringFormatByExtension(data, extension)
        : this.parseToString(data, extension);

    return {
      path,
      data: validatedData
    };
  }

  private parseToString(data, extension) {
    let result;
    if (extension === 'json') {
      result = JSON.stringify(data);
    } else if (extension === 'yaml') {
      result = YAML.stringify(data);
    } else {
      this.generageInvalidFormatError(extension);
    }
    return result;
  }

  private generageInvalidFormatError(extension) {
    throw new Error(
      `Ошибка в инструменте с типом "${
        this.type
      }". Допустимые расширения файла: ${JSON.stringify(
        VALID_EXTENSIONS
      )}. Сформированное значение: ${extension}`
    );
  }

  private changeDataStringFormatByExtension(data, extension) {
    let result;
    let trimmedData = data.trim();

    // llm периодически создает json или yaml с дополнительной запятой. ("{\"data\": \"value\"},\n")
    if(trimmedData.endsWith(',')) {
      trimmedData = trimmedData.slice(0, -1);
    }

    for (let i = 0; i < VALID_EXTENSIONS.length; i++) {
      const validExtension = VALID_EXTENSIONS[i];
      const parser = PARSER[validExtension];
      if(!parser) continue;
      try {
        result = parser.parse(trimmedData);
        return validExtension === extension
          ? trimmedData
          : this.parseToString(result, extension);
      } catch (e) {
        continue;
      }
    }

    throw new Error(
      `Ошибка в инструменте с типом "${this.type}". Некорректный формат данных!`
    );
  }
}
