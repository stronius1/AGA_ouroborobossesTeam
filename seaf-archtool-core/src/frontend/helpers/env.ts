/*
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru

  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      R.Piontik <r.piontik@mail.ru>

  Contributors:
      Navasardyan Suren, Sber - 2023
      R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru> - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2026
*/

import consts from '@front/consts';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {requestToBackend} from '@front/helpers/backend.api.helper';
import {toNumerOrDefault} from '@global/helpers/numberUtils.mjs';

export type TCacheMethods = 'GET' | 'HEAD';
export type TEnvValue = string | undefined;
export type TProcessEnvValues = { [key: string | symbol]: TEnvValue };

export enum Plugins {
  idea = 'idea',
  vscode = 'vscode'
}

export enum CACHE_LEVEL {
  low = 1,
  high = 2
}

const ENV_ERROR_TAG = '[env.dochub]';
const logger = getLoggerWithTag(ENV_ERROR_TAG);

const DEF_METAMODEL_URI_PORTAL = '/metamodel/root.yaml';
const DEF_METAMODEL_URI_IDEA = 'plugin:/idea/metamodel/root.yaml';
const DEFAULT_PROJECT_TITLE = 'SEAF';

let configFromBack;

export default {
  dochub: <TProcessEnvValues>{},
  isPlugin(plugin?: Plugins): boolean {
    const isIdea = !!window.DocHubIDEACodeExt;
    const isVsCode = !!window.DochubVsCodeExt;

    switch (plugin) {
      case Plugins.idea: {
        return isIdea;
      }
      case Plugins.vscode: {
        return isVsCode;
      }
      default: {
        return isIdea || isVsCode;
      }
    }
  },
  get pluginName(): Plugins | undefined {
    if (!this.isPlugin()) {
      return undefined;
    } else if (this.isPlugin(Plugins.idea)) {
      return Plugins.idea;
    } else if (this.isPlugin(Plugins.vscode)) {
      return Plugins.vscode;
    } else {
      return undefined;
    }
  },
  // Адрес backend сервере
  get backendURL(): string {
    return this.dochub?.VUE_APP_DOCHUB_BACKEND_URL || (window?.origin && (window?.origin !== 'null') ? window?.origin : 'http://localhost:3030/');
  },
  // Адрес API доступа к файлам backend сервера
  get backendFileStorageURL(): string {
    return (new URL('/seaf-core/api/core/storage/', this.backendURL)).toString();
  },
  get smartantsMode() {
    return (this.isBackendMode && process.env.VUE_APP_DOCHUB_SMART_ANTS_MODE) ? process.env.VUE_APP_DOCHUB_SMART_ANTS_MODE.toLowerCase() : 'front';
  },
  get isBackendMode() {
    const backendUrl = process.env.VUE_APP_DOCHUB_BACKEND_URL;
    const mode = (process.env.VUE_APP_DOCHUB_MODE || '').toLowerCase().trim();
    return !this.isPlugin() && (backendUrl || (mode === 'backend'));
  },
  get isEnvelopedRequests(): boolean {
    return process.env.VUE_APP_SEAF_ENVELOPED_REQUESTS === 'true';
  },
  get isRolesMode(): boolean {
    return (configFromBack?.roleModeEnabled || process.env.VUE_APP_DOCHUB_ROLES_MODEL || 'N').toUpperCase() === 'Y';
  },
  get isProduction(): boolean {
    return this.dochub.NODE_ENV === 'production';
  },
  get isTraceJSONata(): boolean {
    return (this.dochub.VUE_APP_DOCHUB_JSONATA_ANALYZER || this.additionalIdeEnv?.VUE_APP_DOCHUB_JSONATA_ANALYZER || 'N').toUpperCase() === 'Y';
  },
  get isPerfLoggerEnabled(): boolean {
    return !this.isBackendMode && process?.env?.VUE_APP_DOCHUB_PERF_LOGGER_ENABLE === 'on';
  },
  cacheWithPriority(priority: CACHE_LEVEL): boolean {
    const systemSetting = +this.dochub.VUE_APP_DOCHUB_CACHE_LEVEL;

    if (systemSetting in CACHE_LEVEL) {
      if (this.cache) {
        return systemSetting === priority;
      }
    } else if (systemSetting) {
      logger.error(() => `Неправильно указан параметр "VUE_APP_DOCHUB_CACHE_LEVEL=${systemSetting}" в env!`);
    }

    return false;
  },
  get cache(): TCacheMethods | null {
    const currentMethod = (this.dochub.VUE_APP_DOCHUB_CACHE || 'NONE').toUpperCase();

    if (currentMethod === 'NONE') {
      return null;
    }

    if (['GET', 'HEAD'].includes(currentMethod)) {
      return currentMethod as TCacheMethods;
    }

    throw new Error(`Неправильно указан параметр "VUE_APP_DOCHUB_CACHE=${currentMethod}" в env!`);
  },
  get ideSettings() {
    return (window.DocHubIDEACodeExt || window.DochubVsCodeExt)?.settings;
  },
  get logLevel() {
    return this.ideSettings?.logLevel;
  },
  get isJsonataLogFuncEnable() {
    return this.ideSettings?.isJsonataLogFuncEnable ?? this.dochub.VUE_APP_DOCHUB_JSONATA_LOG_FUNC_ENABLE?.toLowerCase() !== 'off' ?? true;
  },
  // Приходят из настройки env в ide в настройках плагина
  get additionalIdeEnv() {
    return window.additionalIdeEnv;
  },
  get rootDocument(): TEnvValue {
    return this.dochub.VUE_APP_DOCHUB_ROOT_DOCUMENT;
  },
  get rootManifest(): TEnvValue {
    if (this.isPlugin(Plugins.idea)) {
      return consts.plugin.ROOT_MANIFEST;
    } else if (this.isPlugin(Plugins.vscode)) {
      return window.DochubVsCodeExt.rootManifest;
    } else return this.dochub.VUE_APP_DOCHUB_ROOT_MANIFEST;
  },
  get renderCore(): TEnvValue {
    return this.ideSettings?.render?.mode || this.dochub.VUE_APP_DOCHUB_RENDER_CORE || 'graphviz';
  },
  // Переменные систем управления версиями
  get gitlabUrl(): TEnvValue {
    return this.ideSettings?.env?.DOCHUB_IDE_GITLAB_URL || this.dochub.VUE_APP_DOCHUB_GITLAB_URL;
  },
  get bitbucketUrl(): TEnvValue {
    return this.ideSettings?.env?.DOCHUB_IDE_BITBUCKET_URL || this.dochub.VUE_APP_DOCHUB_BITBUCKET_URL;
  },
  get personalToken(): TEnvValue {
    return this.ideSettings?.env?.DOCHUB_IDE_PERSONAL_TOKEN || this.dochub.VUE_APP_DOCHUB_PERSONAL_TOKEN;
  },
  get bitbucketMode(): TEnvValue {
    return this.ideSettings?.env?.DOCHUB_IDE_BITBUCKET_MODE || this.dochub.VUE_APP_DOCHUB_BITBUCKET_MODE;
  },
  get bitbucketWriterMode(): TEnvValue {
    return this.ideSettings?.env?.DOCHUB_IDE_BITBUCKET_WRITER_MODE || this.dochub.VUE_APP_DOCHUB_BITBUCKET_WRITE_MODE || this.bitbucketMode;
  },
  //
  get appendDocHubDocs(): TEnvValue {
    return this.dochub.VUE_APP_DOCHUB_APPEND_DOCHUB_DOCS;
  },
  // Определяет сервер рендеринга
  get plantUmlServer(): TEnvValue {
    let envValue = configFromBack?.plantUmlServer || this.dochub.VUE_APP_PLANTUML_SERVER;
    if (!envValue) {
      envValue = consts.plantuml.DEFAULT_SERVER;
    } else if (envValue === 'ORIGIN') {
      envValue = consts.plantuml.ORIGIN;
    }
    if (this.isPlugin(Plugins.idea)) {
      return this.ideSettings?.isEnterprise ? envValue : (
        this.ideSettings?.render?.external ? this.ideSettings?.render?.server : null
      );
    } else if (this.isPlugin(Plugins.vscode)) {
      return this.ideSettings?.render.server;
    } else return envValue;
  },
  get s3CloudUrl(): string {
    if (this.isPlugin(Plugins.idea)) {
      const url = this.ideSettings?.s3CloudUrl ?? '';
      return `${url}`;
    }
    return configFromBack?.s3CloudUrl || process.env.VUE_APP_DOCHUB_S3_CLOUD_URL || '';
  },
  get usingS3Mode(): boolean {
    if (this.isPlugin(Plugins.idea)) {
      return this.ideSettings?.usingS3Mode ?? false;
    }
    return (configFromBack?.usingS3Mode || process.env.VUE_APP_DOCHUB_USING_S3 || 'N').toUpperCase() === 'Y';
  },
  // Определяет тип запроса к серверу рендеринга
  get plantUmlRequestType(): TEnvValue {
    if (!this.ideSettings?.isEnterprise) {
      if (this.isPlugin(Plugins.idea)) {
        return this.ideSettings?.render?.external ? this.ideSettings?.render?.request_type || 'get' : 'plugin';
      } else if (this.isPlugin(Plugins.vscode)) {
        return this.ideSettings?.render?.request_type || 'get';
      }
    }

    const requestType = (configFromBack?.plantUmlRequestType || this.dochub.VUE_APP_PLANTUML_REQUEST_TYPE)?.toLowerCase() || 'get';

    if (['get', 'post', 'post_compressed'].includes(requestType)) {
      return requestType as TCacheMethods;
    }
    throw new Error(`Неправильно указан параметр "VUE_APP_PLANTUML_REQUEST_TYPE=${requestType}" в env!`);
  },
  get isAppendDocHubDocs(): boolean {
    return (this.appendDocHubDocs || 'y').toLowerCase() === 'y';
  },
  get uriMetamodel(): string {
    let result = this.dochub.VUE_APP_DOCHUB_METAMODEL || DEF_METAMODEL_URI_PORTAL;
    let host = window.location.toString();
    if (this.isPlugin(Plugins.idea)) {
      result = this.ideSettings?.isEnterprise ? result : DEF_METAMODEL_URI_IDEA;
    } else if (this.isPlugin(Plugins.vscode)) {
      if (!this.ideSettings?.isEnterprise && window.DochubVsCodeExt?.metamodelUri) {
        const {scheme, path, authority} = window.DochubVsCodeExt?.metamodelUri;

        result = `${path}`;
        host = `${scheme}://${authority}`;
      } else host = this.ideSettings?.enterpriseServer;
    }
    result = (new URL(result, host)).toString();
    logger.info(() => `Source of metamodel is ${result}`);
    return result;
  },
  get gigachatCredential(): string {
    return this.ideSettings?.gigachatCredential || this.dochub.VUE_APP_GIGACHAT_CREDENTIAL || '';
  },
  get gigachatScope(): string {
    return this.ideSettings?.gigachatScope || this.dochub.VUE_APP_GIGACHAT_SCOPE || '';
  },
  get gigachatDefaultModel(): string {
    return this.ideSettings?.gigachatDefaultModel || this.dochub.VUE_APP_GIGACHAT_DEFAULT_MODEL || null;
  },
  get gigachatTimeout(): number {
    return this.ideSettings?.gigachatTimeout || parseInt(this.dochub.VUE_APP_GIGACHAT_TIMEOUT) || null;
  },
  get gigachatMaxMsgInHistory(): number {
    return toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_MAX_MESSAGE_COUNT_IN_HISTORY, Number.MAX_SAFE_INTEGER);
  },
  get gigachatMaxSumSymbolOfAllMsg(): number {
    return toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_MAX_SUM_SYMBOL_OF_ALL_MESSAGES, Number.MAX_SAFE_INTEGER);
  },
  get gigachatSessionTtl(): number {
    return toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_SESSION_TTL_MS, 900000);
  },

  get clickstreamReportUrl(): string {
    return this.additionalIdeEnv?.VUE_APP_CLICKSTREAM_REPORT_URL || process.env.VUE_APP_CLICKSTREAM_REPORT_URL;
  },
  get clickstreamApiKey(): string {
    return this.additionalIdeEnv?.VUE_APP_CLICKSTREAM_API_KEY || process.env.VUE_APP_CLICKSTREAM_API_KEY;
  },
  get pluginVersion(): string | null {
    return this.ideSettings?.pluginVersion;
  },
  get pluginMode(): string | null {
    if (!this.isPlugin() || !this.ideSettings) {
      return undefined;
    }
    return this.ideSettings.isEnterprise ? 'enterprise' : 'personal';
  },
  get authorityServer(): string | null {
    return configFromBack?.authorityServer || process.env.VUE_APP_DOCHUB_AUTHORITY_SERVER;
  },
  get authorityClientId(): string | null {
    return configFromBack?.authorityClientId || process.env.VUE_APP_DOCHUB_AUTHORITY_CLIENT_ID;
  },
  get authorityScope(): string | null {
    return configFromBack?.authorityScope || process.env.VUE_APP_DOCHUB_AUTHORITY_SCOPE;
  },
  get archChooserEnabled(): boolean {
    return configFromBack?.archChooser || false;
  },
  get backendEnv() {
    return configFromBack;
  },
  async updateBackendEnv() {
    configFromBack = await requestToBackend('/seaf-core/api/env-config', {}, null);
  },
  get isCacheMode(): boolean {
    if (this.isPlugin()) {
      return this.ideSettings?.isCacheMode;
    }
    return false;
  },
  get projectTitle(): string {
    return typeof process?.env?.VUE_APP_DOCHUB_TITLE === 'string' ? process.env.VUE_APP_DOCHUB_TITLE : DEFAULT_PROJECT_TITLE;
  }
 };
