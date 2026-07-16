/*
  Copyright (C) 2026 Sber

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
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
*/

export const FILE_STATUS_LABELS = {
  RECEIVED:          'Получен',
  VALIDATING_UPLOAD: 'Проверка',
  VALIDATION_RETRY:  'Повторная проверка',
  UPLOAD_REJECTED:   'Отклонён',
  STORED_S3:         'Сохранён',
  EXPIRED:           'Не доступен'
};

export const VALIDATOR_STATUS_LABELS = {
  PENDING: 'Ожидает',
  PASSED:  'Пройдена',
  FAILED:  'Не пройдена',
  RETRY:   'Повтор'
};

export const HIGHLIGHT_LABELS_RU = {
  NEW:     'НОВЫЙ',
  UPDATED: 'ОБНОВЛЁН',
  ERROR:   'ОШИБКА'
};

export function fileStatusLabel(status) {
  if (!status) return '';
  return FILE_STATUS_LABELS[String(status).toUpperCase()] || String(status);
}

export function validatorStatusLabel(status) {
  if (!status) return '';
  return VALIDATOR_STATUS_LABELS[String(status).toUpperCase()] || String(status);
}
export function highlightLabelRu(type) {
  if (!type) return '';
  return HIGHLIGHT_LABELS_RU[String(type).toUpperCase()] || '';
}
