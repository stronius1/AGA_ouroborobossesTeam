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
      Alexander Romashin, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import * as fs from 'fs';
import {Agent, AgentOptions} from 'node:https';
import {GigaChatClientConfig} from 'gigachat';

const httpsAgent = (options?: AgentOptions, ca_bundle_file?: string, cert_file?: string, key_file?: string): Agent => {

  if (ca_bundle_file && fs.existsSync(ca_bundle_file)) {
    options.ca = fs.readFileSync(ca_bundle_file);
  }

  if (cert_file && key_file && fs.existsSync(cert_file) && fs.existsSync(key_file)) {
    options.cert = fs.readFileSync(cert_file);
    options.key = fs.readFileSync(key_file);
  }

  return new Agent(options);
};

export const gigachatOptions = (options?: GigaChatClientConfig): GigaChatClientConfig => {
  if (!options) options = {};

  // Добавляем HTTPS агента
  const ca_bundle_file = process.env.VUE_APP_GIGACHAT_CA_BUNDLE_FILE;
  const cert_file = process.env.VUE_APP_GIGACHAT_CERT_FILE;
  const key_file = process.env.VUE_APP_GIGACHAT_KEY_FILE;

  if (!process.env.VUE_APP_GIGACHAT_CREDENTIAL && ca_bundle_file && cert_file && key_file) {
    options.httpsAgent = httpsAgent({}, ca_bundle_file, cert_file, key_file);
  } else if(ca_bundle_file) {
    options.httpsAgent = httpsAgent({}, ca_bundle_file);
  } else {
    options.httpsAgent = httpsAgent();
  }

  // Добавляем base_url, если он задан
  if (process.env.VUE_APP_GIGACHAT_BASE_URL) {
    options.baseUrl = process.env.VUE_APP_GIGACHAT_BASE_URL;
  }
  // Добавляем auth_url, если он задан
  if (process.env.VUE_APP_GIGACHAT_AUTH_URL) {
    options.authUrl = process.env.VUE_APP_GIGACHAT_AUTH_URL;
  }
  // Устанавливаем креды Гигачата
  if (process.env.VUE_APP_GIGACHAT_CREDENTIAL && process.env.VUE_APP_GIGACHAT_SCOPE) {
    options.credentials = process.env.VUE_APP_GIGACHAT_CREDENTIAL;
    options.scope = process.env.VUE_APP_GIGACHAT_SCOPE;
  }
  // Устанавливаем дефолтные настройки модели
  if (process.env.VUE_APP_GIGACHAT_DEFAULT_MODEL) {
    options.model = process.env.VUE_APP_GIGACHAT_DEFAULT_MODEL;
  }
  // Устанавливаем таймаут ответа Гигачата
  if (process.env.VUE_APP_GIGACHAT_TIMEOUT) {
    options.timeout = parseInt(process.env.VUE_APP_GIGACHAT_TIMEOUT);
  }

  return options;
};
