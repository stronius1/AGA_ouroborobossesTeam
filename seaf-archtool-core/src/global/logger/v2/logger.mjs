/*
  Copyright (C) 2025 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

/**
 * Тут храним текущий логгер, который возвращается при вызове getLogger или getLoggerWithTag
 * По дефолту пустой логгер
 */
let currentLogger = {
  // Это заглушка для логгера до установки нормального. Нормальный логгер устанавливает фронт или бек
  /* eslint-disable no-unused-vars,@typescript-eslint/no-empty-function */
  error: (tag, msgFn, error) => {},
  warn: (tag, msgFn, error) => {},
  info: (tag, msgFn, error) => {},
  debug: (tag, msgFn, error) => {},
  trace: (tag, msgFn, error) => {},
  setLevel: (level) => {
      return {
          isSuccess: false,
          message: 'logger impl not set'
      };
  },
  getLevelName: () => 'off'
  /* eslint-enable no-unused-vars,@typescript-eslint/no-empty-function */
};

/**
 * Смена текущего логгера
 * Бек или фронт должны одним из первых действий установить свой логгер
 * Далее любой потребитель может получить установленный логгер методами getLogger или getLoggerWithTag
 * @param logger - логгер
 */
export function changeLoggerImpl(logger) {
  currentLogger = logger;
}

/**
 * Метод для оборачивания логгера и добавления во все методы тега, чтобы не передавать его каждый раз
 * @param tag - тег для логгера
 * @param logger - логгер, в который будет добавлен тег
 */
export function wrapLoggerWithTag(tag, logger) {
  return {
    error: (msgFn, error) => logger.error(tag, msgFn, error),
    warn: (msgFn, error) => logger.warn(tag, msgFn, error),
    info: (msgFn, error) => logger.info(tag, msgFn, error),
    debug: (msgFn, error) => logger.debug(tag, msgFn, error),
    trace: (msgFn, error) => logger.trace(tag, msgFn, error),
    setLevel: (level) => logger.setLevel(level),
    getLevelName: () => logger.getLevelName()
  };
}

/**
 * Возвращает текущий основной логгер.
 * Фронт или бек должны установить используемый логгер в начале работы с помощью changeLoggerImpl
 */
export function getLogger() {
    return {
    error: (tag, msgFn, error) => currentLogger.error(tag, msgFn, error),
    warn: (tag, msgFn, error) => currentLogger.warn(tag, msgFn, error),
    info: (tag, msgFn, error) => currentLogger.info(tag, msgFn, error),
    debug: (tag, msgFn, error) => currentLogger.debug(tag, msgFn, error),
    trace: (tag, msgFn, error) => currentLogger.trace(tag, msgFn, error),
    setLevel: (level) => currentLogger.setLevel(level),
    getLevelName: () => currentLogger.getLevelName()
  };
}

/**
 * Доп функция для удобства, вызова 1 строкой.
 * Возвращает текущий логгер с установленным тегом
 */
export function getLoggerWithTag(tag) {
    return wrapLoggerWithTag(tag, getLogger());
}
