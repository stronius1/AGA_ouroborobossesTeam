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
      Alexander Romashin, Sber

  Contributors:
      Alexander Romashin, Sber
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import { PullDataToolFn } from '@global/gigachat/agent/type/PullDataToolFn';
import datasets from '../datasets.mjs';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { AgentConfig } from '@global/gigachat/agent/type/AgentConfig';

const logger = getLoggerWithTag('pullDataTool');

export const getPullDataTool = (
  storage,
  roleId,
  agentConfig?: AgentConfig
): PullDataToolFn => {
  logger.debug(
    () =>
      `Init function. Has storage: ${Boolean(storage)}. Storage hash: ${
        storage.hash ?? null
      }`
  );

  const pullDataTool = async(
    query: string,
    params?: any,
    originArg?: any,
    config = agentConfig
  ): Promise<any> => {
    logger.debug(
      () =>
        `Has storage: ${Boolean(storage)}. Storage hash: ${
          storage?.hash
        }. Role: ${roleId}. Has config: ${Boolean(
          config
        )}. Has manifest: ${Boolean(
          roleId ? storage.manifests[roleId] : storage.manifest
        )}`
    );

    // Поддержка origin как в presentations: используем tool-origin приоритетно, затем конфигурационный
    const resolvedParams =
      params ?? (config as any)?.jsonataParams ?? undefined;
    const origin = originArg ?? (config as any)?.jsonataOrigin;

    // Создаем массив для сбора логов
    const logEntries: Array<{ content: any; tag?: string; timestamp: number }> =
      [];

    // Создаем кастомную функцию log для сбора логов
    const logFunction = (content: any, tag?: string) => {
      const logEntry = {
        content: content,
        tag: tag,
        timestamp: Date.now()
      };
      // Добавляем в массив логов
      logEntries.push(logEntry);
      // Выводим лог в консоль сервера (для отладки)
      logger.debug(() => `[gigachat-log] ${JSON.stringify(content, null, 2)}`);
      // Возвращаем значение как обычно для JSONata
      return content;
    };

    if (origin) {
      // Используем datasets API напрямую как в presentations
      const datasetsInstance = datasets(storage, roleId);

      if (typeof origin === 'string') {
        // Тип 1: origin: "dataset_id" или JSONata запрос
        let originData;

        if (origin.startsWith('(') || origin.startsWith('$')) {
          // JSONata запрос - выполняем его в контексте манифеста
          const manifest = roleId
            ? storage.manifests[roleId]
            : storage.manifest;
          originData = await datasetsInstance.parseSource(
            manifest,
            origin,
            undefined,
            resolvedParams
          );
        } else {
          // Идентификатор датасета
          originData = await datasetsInstance.releaseData(
            `/datasets/${origin}`,
            resolvedParams
          );
        }

        // Выполняем основной запрос с кастомной функцией log
        const queryDriver = datasetsInstance.jsonataDriver.expression(
          `(${query})`,
          undefined,
          resolvedParams,
          false,
          { log: logFunction }
        );
        const result = await queryDriver.evaluate(originData);

        // Возвращаем результат с логами
        return { result, logs: logEntries };
      } else if (Array.isArray(origin)) {
        // Массив датасетов или JSONata запросов: загружаем все и объединяем как объект с ключами-идентификаторами
        const originData = {};
        const manifest = roleId ? storage.manifests[roleId] : storage.manifest;

        await Promise.all(
          origin.map(async(sourceValue) => {
            if (typeof sourceValue === 'string') {
              if (sourceValue.startsWith('(') || sourceValue.startsWith('$')) {
                // JSONata запрос - выполняем в контексте манифеста, используем запрос как ключ
                originData[sourceValue] = await datasetsInstance.parseSource(
                  manifest,
                  sourceValue,
                  undefined,
                  resolvedParams
                );
              } else {
                // Идентификатор датасета
                originData[sourceValue] = await datasetsInstance.releaseData(
                  `/datasets/${sourceValue}`,
                  resolvedParams
                );
              }
            } else {
              // Прямое значение - используем JSON представление как ключ
              const key = JSON.stringify(sourceValue);
              originData[key] = sourceValue;
            }
          })
        );

        // Выполняем JSONata запрос с кастомной функцией log
        const queryDriver = datasetsInstance.jsonataDriver.expression(
          `(${query})`,
          undefined,
          resolvedParams,
          false,
          { log: logFunction }
        );
        const result = await queryDriver.evaluate(originData);

        // Возвращаем результат с логами
        return { result, logs: logEntries };
      } else if (typeof origin === 'object') {
        // Тип 2: origin: {systems: "dataset_id", integrations: "dataset_id", manifest: "($)"}
        // В контексте query ($) доступен объект: {systems: данные, integrations: данные, manifest: данные}
        const originData = {};
        const manifest = roleId ? storage.manifests[roleId] : storage.manifest;

        for (const [key, sourceValue] of Object.entries(origin)) {
          if (typeof sourceValue === 'string') {
            if (sourceValue.startsWith('(') || sourceValue.startsWith('$')) {
              // JSONata запрос - выполняем в контексте манифеста
              originData[key] = await datasetsInstance.parseSource(
                manifest,
                sourceValue,
                undefined,
                resolvedParams
              );
            } else {
              // Идентификатор датасета
              originData[key] = await datasetsInstance.releaseData(
                `/datasets/${sourceValue}`,
                resolvedParams
              );
            }
          } else {
            // Прямое значение
            originData[key] = sourceValue;
          }
        }

        // Выполняем JSONata запрос с кастомной функцией log
        const queryDriver = datasetsInstance.jsonataDriver.expression(
          `(${query})`,
          undefined,
          resolvedParams,
          false,
          { log: logFunction }
        );
        const result = await queryDriver.evaluate(originData);

        // Возвращаем результат с логами
        return { result, logs: logEntries };
      }
    }

    // Обычный JSONata запрос без origin, но с поддержкой $log()
    const datasetsInstance = datasets(storage, roleId);
    const queryDriver = datasetsInstance.jsonataDriver.expression(
      `(${query})`,
      undefined,
      resolvedParams,
      false,
      { log: logFunction }
    );
    const manifest = roleId ? storage.manifests[roleId] : storage.manifest;
    const result = await queryDriver.evaluate(manifest);

    // Возвращаем результат с логами
    return { result, logs: logEntries };
  };

  return pullDataTool;
};
