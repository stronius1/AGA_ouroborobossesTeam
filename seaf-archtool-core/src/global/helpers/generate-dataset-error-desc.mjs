/*
  Copyright (C) 2023 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

const DEFAULT_ERROR_MESSAGE = 'Непредвиденная ошибка';

const createDatasetTreeMessage = (id, datasetsWithError, manifest, message = '', deepSize = 0) => {
  const error = datasetsWithError?.[id]?.error;
  if(!error) return message;

  const padding = '  '.repeat(deepSize);
  const errorMessage = error?.message || error?.code || error?.response?.data || DEFAULT_ERROR_MESSAGE;

  const uri = datasetsWithError[id]?.uri;

  message +=
    ('\n' + padding + `id: ${id}`) +
    (uri ? ('\n' + padding + `uri: ${uri}`) : '') +
    ('\n' + padding + `error: ${errorMessage}`);

  const origin = manifest?.datasets?.[id]?.origin;
  if(!origin) return message;

  const originList = typeof origin === 'string'
    ? [origin]
    : Object.values(origin);

  const originWithError = originList
    .filter(datasetId => datasetsWithError?.[datasetId]?.error);

  if (originWithError.length > 0) {
    message += '\n' + padding + 'origin:';

    for (let i = 0; i < originWithError.length; i++) {
      const datasetId = originWithError[i];
      message = createDatasetTreeMessage(datasetId, datasetsWithError, manifest, message, deepSize + 1);
    }
  }

  return message;
};

const checkForAnErrorsInOrigin = (id, datasetsWithError, manifest) => {
  if(!datasetsWithError?.[id]) return false;

  const datasetOrigin = manifest?.datasets?.[id]?.origin;
  const origin = datasetOrigin
    ? typeof  datasetOrigin === 'string'
      ? [datasetOrigin]
      : Object.values(datasetOrigin)
    : [];

  return origin.filter(id => datasetsWithError[id]).length > 0;
};

export default function generateDatasetErrorDesc(id, error, datasetsWithError, manifest) {
  let output = `Ошибка при обсчёте датасета ${id}.\n${
    typeof error === 'string' ? error : error?.message ?? ''
  }`;
  if (error?.code) {
    output += `\nКод ошибки: ${error.code}.`;
  }
  if (error?.value) {
    output += `\nЗаписанное значение: ${error.value}.`;
  }
  if (error?.position) {
    output += `\nНа позиции ${error.position}.`;
  }
  if (error?.token) {
    output += `\nОшибочный токен: ${error.token}.`;
  }
  if (error?.response?.data) {
    output += `\n${error?.response?.data}.`;
  }
  if (error?.uri) {
    output += `\n${error?.uri}.`;
  }
  if (checkForAnErrorsInOrigin(id, datasetsWithError, manifest)) {
    const stackMessage = createDatasetTreeMessage(id, datasetsWithError, manifest);
    output += `\n\nСтек датасетов c ошибкой:\n${stackMessage}`;
  }
  return output;
}
