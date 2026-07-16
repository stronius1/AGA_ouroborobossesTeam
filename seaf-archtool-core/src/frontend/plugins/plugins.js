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
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
*/

/* Модуль Vuex для работы с плагинами */
import requests from '@front/helpers/requests';
import env from '@front/helpers/env';
import {getLogger, getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/p/plugins');

let appInstance = null;

export function setPluginsStoreAppInstance(app) {
  appInstance = app;
}

const plugins = {
	documents: [],
	// Все ранее зарегистрированные плагины переносим в основной менеджер
	pull() {
		this.documents.forEach((el) => DocHub.documents.register(el.type, el.component));
	}
};

// Регистрируем временный менеджер регистрации плагинов
window.DocHub = {
	documents: {
		register(type, component) {
			plugins.documents.push({ type, component });
		},
		fetch() {
			return JSON.parse(JSON.stringify(plugins.documents));
		},
		getLoggerWithTag(pluginName) {
      return getLoggerWithTag(`plugin/${pluginName}`);
    },
		getLogger() {
      return getLogger();
    }
	}
};

export default {
	namespaced: true,
	state: {
		ready: false, // Признак готовности плагинов к использованию
		documents: {}
	},
	mutations: {
		setReady(state, value) {
			state.ready = value;
		},
		registerDocument(state, document) {
			state.documents[document.type] = document.component;
		}
	},
	actions: {
		// Загружаем плагины
		init(context) {
			// Регистрируем менеджер документов для плагинов
			window.DocHub.documents.register = function(type, component) {
        component.mixins = component.mixins || [];

        if (!appInstance) {
          throw new Error('Vue app instance is not initialized for plugin registration');
        }

        appInstance.component(`plugin-doc-${type}`, component);
				context.commit('registerDocument', { type, component });
			};
			// Регистрируем функцию получения доступных типов документов
			window.DocHub.documents.fetch = () => {
				return JSON.parse(JSON.stringify(Object.keys(context.state.documents || {})));
			};
			plugins.pull();

			let counter = 0;

			// Получаем данные манифеста приложения
			!env.isPlugin() && requests.request('/manifest.json', new URL('/', window.location)).then((response) => {
				(response?.data?.plugins || []).map((url) => {
					counter++;

					const decCounter = () => !(--counter) && context.commit('setReady', true);

					const script = document.createElement('script');
					script.src = url;
					script.onload = function() {
						logger.info(() => `Плагина [${url}] успешно подключен`);
						decCounter();
					};
					script.onerror = (e) => {
						logger.error(() => `Ошибка загрузки плагина [${url}]`, e);
						decCounter();
					};
					document.head.appendChild(script);

					if (!counter) context.commit('setReady', true);
				});
			}).catch((e) => {
				logger.error(() => 'Не удалось загрузить манифест приложения', e);
				context.commit('setReady', true);
			});
		}
	}
};
