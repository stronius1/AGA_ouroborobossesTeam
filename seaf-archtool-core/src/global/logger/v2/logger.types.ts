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
 * Модель дответа при смене уровня логирования
 */
export interface ChangeLevelResult{
  isSuccess: boolean,
  message: string
}

/**
 * Общий интерфейс для логгера
 */
export interface SeafLogger {
  error (tag: string, msgFn: LogMessageFn, error?: unknown): void;
  warn (tag: string, msgFn: LogMessageFn, error?: unknown): void;
  info (tag: string, msgFn: LogMessageFn, error?: unknown): void;
  debug (tag: string, msgFn: LogMessageFn, error?: unknown): void;
  trace (tag: string, msgFn: LogMessageFn, error?: unknown): void;
  setLevel (level: string): ChangeLevelResult;
  getLevelName (): string;
}

/**
 * Обертка для общего интерфейса логгера, но можно передать тег при создании и дальше его не указывать
 */
export interface SeafTaggedLogger {
  error (msgFn: LogMessageFn, error?: unknown): void;
  warn (msgFn: LogMessageFn, error?: unknown): void;
  info (msgFn: LogMessageFn, error?: unknown): void;
  debug (msgFn: LogMessageFn, error?: unknown): void;
  trace (msgFn: LogMessageFn, error?: unknown): void;
  setLevel (level: string): ChangeLevelResult;
  getLevelName (): string;
}

/**
 * интерфейс для передачи на логирование объекта с заголовком.
 * Перед записью в лог объект будет обернут в вызов JSON.stringify
 * Подробнее тут -> logMessageToStringArray.mjs
 */
export interface LogWithObject {
  title: string,
  obj: object
}

// Тип для функции-сообщения
export type LogMessageFn = () => string | (string | LogWithObject)[] | undefined
