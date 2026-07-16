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
*/

import {GigaChatClientConfig} from 'gigachat';
import env, {Plugins} from '../env';

export const gigachatOptions = async(options?: GigaChatClientConfig): Promise<GigaChatClientConfig> => {
  if (!options) options = {};
  if(env.gigachatDefaultModel) {
    options.model = env.gigachatDefaultModel;
  }
  if(env.gigachatTimeout) {
    options.timeout = env.gigachatTimeout;
  }
  return {
    ...options,
    credentials: env.gigachatCredential,
    scope: env.gigachatScope,
    ...env.isPlugin(Plugins.idea) ? await ideaPluginOptions() : devServerOptions()
  };
};

const ideaPluginOptions = async() => {
  const {port} = await window.$PAPI.startGigachatProxy();
  return {
    dangerouslyAllowBrowser: true,
    authUrl: `http://localhost:${port}/oauth`,
    baseUrl: `http://localhost:${port}`
  };
};

const devServerOptions = () => {
  return {
    dangerouslyAllowBrowser: true,
    authUrl: '/oauth',
    baseUrl: ''
  };
};
