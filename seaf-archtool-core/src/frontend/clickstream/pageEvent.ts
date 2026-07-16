/*
 *    Copyright (C) 2025 Sber
 *
 *    Licensed under the Apache License, Version 2.0 (the "License");
 *    you may not use this file except in compliance with the License.
 *    You may obtain a copy of the License at
 *
 *            http://www.apache.org/licenses/LICENSE-2.0
 *
 *    Unless required by applicable law or agreed to in writing, software
 *    distributed under the License is distributed on an "AS IS" BASIS,
 *    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *    See the License for the specific language governing permissions and
 *    limitations under the License.
 *
 *    Maintainers:
 *      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
 *
 *    Contributors:
 *      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
 */

import {sendEvent} from '@sbol/clickstream-agent';
import env from '@front/helpers/env';
import { v4 as uuidv4 } from 'uuid';
import {
  getClickstreamState,
  platform,
  PAGE_FROM_PATH_SESSION_STORE_KEY,
  PAGE_TO_PATH_SESSION_STORE_KEY,
  PAGE_LOAD_START_SESSION_STORE_KEY, ROUTE_UID_SESSION_STORE_KEY, ClickstreamState
} from '@front/clickstream/clickstream';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('cs/pageEvent.ts');

/**
 * Информация о загрузке одной страницы
 */
interface PageLoadEvent {
  /**
   * UUID перехода на страницу
   */
  routeUUID: string,
  /**
   * Путь предыдущей страницы без домена
   */
  fromPage: string,
  /**
   * Путь текущей страницы без домена
   */
  toPage: string,
  /**
   * Название основного компонента на странице
   */
  rootComponentName: string,
  /**
   * Уникальный идентификатор (UID) основного компонента на странице
   */
  rootComponentUid: number,
  /**
   * Время начала рендеринга страницы
   */
  startTime: number,
  /**
   * Количество документов, которые предстоит отрисовать на странице
   */
  docCount: number,
  /**
   * Количество документов, которые уже закончили свою отрисовку
   */
  docLoaded: number,
  /**
   * Промежуток времени, который нужно выждать перед отправкой события,
   * на случай появления нового компонента позднее. Если новый компонент появился,
   * счётчик завершенных документов увеличивается, и снова ожидаем окончания его рендеринга.
   * Таймер в таком случае перезапускается.
   */
  waitToSendMs: number,
  /**
   * Здесь сохраняется время отрисовки последнего документа при задании интервала ожидания (waitToSendMs).
   * Если ожидаемый компонент не появляется за указанный интервал, считается, что страница загружена полностью,
   * и отправляется событие в систему аналитики.
   */
  potentialEndTime: number | null,

  /**
   * Таймаут отправки события в аналитику. Используется, если все известные компоненты были отрисованы,
   * однако существует установленный таймер ожидания новых компонентов. Создается временная задержка (setTimeout)
   * для отправки события. Задержка отменяется, если обнаруживается новый компонент, иначе по истечению времени
   * событие отправляется в аналитику.
   */
  waitToSendTimeout: ReturnType<typeof setTimeout> | null;
}

/**
 * Данные текущего отслеживаемого события загрузки страницы
 */
let pageLoadEvent: PageLoadEvent | null;

/**
 * Метод сброса таймаута отправки события
 */
function __resetTimeout(event: PageLoadEvent) {
  if (event && event.waitToSendTimeout) {
    logger.trace(() => 'wait timeout removed, waitToSendMs set to 0, potentialEndTime set to null');
    clearTimeout(event.waitToSendTimeout);
    event.waitToSendTimeout = null;
    event.waitToSendMs = 0;
    event.potentialEndTime = null;
  }
}

/**
 * Считаем в какой промежуток попадает время загрузки
 * @param loadTimeMs - время загрузки
 * @return Константа описывающая время загрузки
 */
function __calcTimeRange(loadTimeMs: number): string {
  if (loadTimeMs <= 3_000) return 'Excellent';
  if (loadTimeMs <= 6_000) return 'Good';
  if (loadTimeMs <= 10_000) return 'Poor';
  return 'Critical';
}

/**
 * Начало процесса сбора данных для события загрузки страницы.
 *
 * Мы дожидаемся полной загрузки всех компонентов на странице и лишь затем отправляем событие в аналитический сервис.
 * Именно отсюда начинается подсчёт для новой страницы.
 *
 * @param {string} componentName — название компонента, отвечающего за отображение страницы
 * @param {string} uid — уникальный идентификатор корневого компонента
 */
export const startPageEvent = (componentName: string, uid: number) => {
  if (getClickstreamState() === ClickstreamState.CannotStart) {
    logger.trace(() => 'clickstream не запущен (CannotStart), не можем начать отслеживание события');
    return;
  }

  const routeUUID = sessionStorage.getItem(ROUTE_UID_SESSION_STORE_KEY) || uuidv4();
  if (pageLoadEvent && pageLoadEvent.routeUUID === routeUUID) {
    // Так как мы находимся на той же странице, то пропускаем создание нового события
    return;
  }

  if (pageLoadEvent) { // если страница поменялась, но старое событие почему-то не отправилось, отправим вручную
    logger.trace(() => 'start new page, but old event not ended, send it manually');
    sendPageLoadEvent(pageLoadEvent);
  }
  // Записи в sessionStorage отсутствуют, значит запуск выполняется, вероятно, из ide. Применяются стандартные значения настроек.
  const startTimeFromSS = sessionStorage.getItem(PAGE_LOAD_START_SESSION_STORE_KEY);
  const startTime = startTimeFromSS ? Number(startTimeFromSS) : Date.now();
  const fromPage = sessionStorage.getItem(PAGE_FROM_PATH_SESSION_STORE_KEY) || '/';
  const toPage = sessionStorage.getItem(PAGE_TO_PATH_SESSION_STORE_KEY) || '/';
  pageLoadEvent = {
    routeUUID: routeUUID,
    fromPage: fromPage,
    toPage: toPage,
    rootComponentName: componentName,
    rootComponentUid: uid,
    startTime: startTime,
    docCount: 0,
    docLoaded: 0,
    waitToSendMs: 0,
    potentialEndTime: null,
    waitToSendTimeout: null
  };
  logger.trace(() => `start page Event: ${JSON.stringify(pageLoadEvent)}`);
};

/**
 * Регистрация компонента в событии для последующего ожидания его полного рендеринга
 */
export const pageEventRegDoc = () => {
  __resetTimeout(pageLoadEvent);
  if (pageLoadEvent) {
    pageLoadEvent.docCount++;
  }
  logger.trace(() => `pageEventRegDoc eval? : ${(!!pageLoadEvent)}`);
};

/**
 * Настройка таймера ожидания возможных новых компонентов
 *
 * @param {number} ms — количество миллисекунд задержки перед отправкой события
 */
export const waitNextDoc = (ms: number) => {
  if (pageLoadEvent) {
    pageLoadEvent.waitToSendMs = ms;
    logger.trace(() => `waitNextDoc set ms: ${ms}`);
  }
};

/**
 * Подтверждение завершения рендеринга конкретного компонента.
 *
 * После того как все зарегистрированные компоненты успешно отрисуются, событие будет немедленно отправлено
 * или отложено с использованием таймера.
 */
export const pageEventDocOnLoad = () => {
  logger.trace(() => `pageEventDocOnLoad eval? : ${(!!pageLoadEvent)}`);
  if (pageLoadEvent) {
    pageLoadEvent.docLoaded++;
    if (pageLoadEvent.docLoaded >= pageLoadEvent.docCount) {
      if (pageLoadEvent.waitToSendMs > 0) {
        logger.trace(() => `for event wait timeout exist, then not send immediately, create wait next event timeout with ${pageLoadEvent.waitToSendMs} ms`);
        // Установлен таймер ожидания нового компонента, поэтому делаем отложенную отправку события, если новый компонент успеет появиться,
        // то событие будет ждать завершения его отрисовки иначе отправится по расписанию.
        clearTimeout(pageLoadEvent.waitToSendTimeout);
        pageLoadEvent.potentialEndTime = Date.now();
        pageLoadEvent.waitToSendTimeout = setTimeout(() => sendPageLoadEvent(pageLoadEvent), pageLoadEvent.waitToSendMs);
      } else {
        sendPageLoadEvent(pageLoadEvent);
      }
    }
  }
};

/**
 * Непосредственная отправка события в аналитику
 */
function sendPageLoadEvent(event: PageLoadEvent) {
  if (getClickstreamState() !== ClickstreamState.Running) {
    logger.trace(() => 'clickstream не запущен (!= Running), не можем отправить событие' +
        (env.isPlugin() ? ', мы в плагине, запуск clickstream может быть позже, после получения всех настроек' : '')
    );
    pageLoadEvent = null;
    return;
  }
  __resetTimeout(event);
  const endTime = event.potentialEndTime || Date.now();
  logger.trace(() => `sendPageLoadEvent endTime = [${endTime}], event = [${JSON.stringify(event)}]`);
  const loadTimeMs = endTime - event.startTime;
  const timeRange = __calcTimeRange(loadTimeMs);
  const eventProperties = [{
    key: 'targetFullPath',
    value: event.toPage
  }, {
    key: 'fromFullPath',
    value: event.fromPage
  }, {
    key: 'platform',
    value: platform
  }, {
    key: 'loadTimeMs',
    value: String(loadTimeMs)
  }, {
    key: 'loadTimeRange',
    value: timeRange
  }, {
    key: 'componentName',
    value: event.rootComponentName
  }, {
    key: 'allComponentLoad',
    value: (event.docCount === event.docLoaded).toString()
  }];
  const pluginVersion = env.pluginVersion;
  if (pluginVersion) {
    eventProperties.push({
      key: 'pluginVersion',
      value: pluginVersion
    });
  }
  sendEvent({
    eventCategory: 'general',
    eventAction: 'page_view',
    value: event.toPage,
    properties: eventProperties
  }).catch(e => {
    logger.warn(() => 'Ошибка отправки события page_view в clickstream:', e);
  });
  sendEvent({
    eventCategory: 'general',
    eventAction: 'page_view_timing',
    value: timeRange,
    properties: eventProperties
  }).catch(e => {
    logger.warn(() => 'Ошибка отправки события timing в clickstream:', e);
  });
  if (event.rootComponentUid === pageLoadEvent.rootComponentUid) {
    // Если обработанное событие соответствует последнему отправленному нами событию, очищаем его.
    // Если начато новое событие (например, с другим uid), не вмешиваемся в его обработку.
    pageLoadEvent = null;
  }
}
