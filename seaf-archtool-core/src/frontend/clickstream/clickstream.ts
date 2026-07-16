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

import env, {Plugins} from '@front/helpers/env';
import {userIdentifiersStoreSeafPlugin} from '@front/clickstream/userIdentityStoreSeaf';
import {setConfig, setMeta, setProfile} from '@sbol/clickstream-agent';
import {getUserHash} from '@front/clickstream/userHashStore';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

/**
 * Ключ для хранения времени начала загрузки страницы в session storage
 */
export const PAGE_LOAD_START_SESSION_STORE_KEY = 'cs_pageLoadStart';
/**
 * Ключ для хранения страницы с которой совершен переход в session storage
 */
export const PAGE_FROM_PATH_SESSION_STORE_KEY = 'cs_pageFromPath';
/**
 * Ключ для хранения страницы на которую совершен переход в session storage
 */
export const PAGE_TO_PATH_SESSION_STORE_KEY = 'cs_pageToPath';
/**
 * Ключ для хранения uuid, который обновляется при каждом переходе на новую страницу в session storage
 */
export const ROUTE_UID_SESSION_STORE_KEY = 'cs_routeUid';

export enum ClickstreamState {
  Initializing = 'initializing',
  Running = 'running',
  CannotStart = 'cannot_start'
}

/**
 * рубильник, указывающий, что clickstream был корректно инициализирован
 */
let clickstreamState: ClickstreamState = ClickstreamState.Initializing;
export const getClickstreamState = (): ClickstreamState => clickstreamState;

/**
 * Платформа, в которой на данный момент работает модуль, для отправки в clickstream
 */
export const platform = !env.isPlugin() ? 'web' : env.isPlugin(Plugins.idea) ? 'plugin_idea' : 'plugin_vscode';

const logger = getLoggerWithTag('cs/clickstream.ts');

/**
 * Инициализация clickstream
 */
export const enableClickstream = async() => {
  if (env.isPlugin(Plugins.vscode)) {
    logger.info(() => 'Для vscode clickstream пока не работает');
    clickstreamState = ClickstreamState.CannotStart;
    return;
  }
  let reportUrl = env.clickstreamReportUrl;
  let apiKey = env.clickstreamApiKey;
  if (env.isBackendMode) {
    const configFromBack = env.backendEnv;
    if (configFromBack?.clickstreamReportUrl && configFromBack?.clickstreamApiKey) {
      reportUrl = configFromBack.clickstreamReportUrl;
      apiKey = configFromBack.clickstreamApiKey;
    } else {
      logger.info(() => [
          'Конфигурация clickstream с backend не пришла или пришла не корректная, не указан один или оба параметра ' +
          '(clickstreamReportUrl, clickstreamApiKey) используем параметры frontend',
        {title: 'clickstreamReportUrl', obj: configFromBack?.clickstreamReportUrl},
        {title: 'clickstreamApiKey', obj: configFromBack?.clickstreamApiKey}
      ]);
    }
  }
  if (!reportUrl || !apiKey) {
    logger.info(() => 'Настройки clickstream (VUE_APP_CLICKSTREAM_REPORT_URL и VUE_APP_CLICKSTREAM_API_KEY) ' +
      'не указаны в переменных окружения, запуск clickstream невозможен.'
    );
    clickstreamState = ClickstreamState.CannotStart;
    return;
  }

  try {
    const userHash = await getUserHash();
    setConfig({
      reportUrl: reportUrl,
      userIdentifiersStore: env.isPlugin() ? userIdentifiersStoreSeafPlugin : null
    });

    setMeta({
      apiKey: apiKey
    });

    setProfile({
      hashUserLoginId: userHash,
      appVersion: __APP_VERSION__
    });

    clickstreamState = ClickstreamState.Running;

    logger.info(() => 'clickstream запущен.');
  } catch (e: any) {
    logger.error(() => 'Произошла ошибка при старте механизма отправки событий в clickstream.');
    clickstreamState = ClickstreamState.CannotStart;
    return;
  }
};
