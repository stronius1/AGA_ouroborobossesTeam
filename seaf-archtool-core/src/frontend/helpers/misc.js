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
      Navasardyan Suren, Sber - 2022
      R.Piontik <r.piontik@mail.ru> - 2022
*/

import mustache from 'mustache/mustache';
import requests from '@front/helpers/requests';
import { asyncApiStyles } from '@front/components/Docs/styles/asyncapi';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/h/misc');

const isObjectEmpty = obj => Object.entries(obj).length === 0 && obj.constructor === Object;

const warn = msg => {
    logger.warn(() => msg);
	return null;
};

const convertVNodeArray = (h, wrapperTag, nodes) => {
	if (nodes.length > 1 || !nodes[0].tag) {
		return h(wrapperTag, {}, nodes);
	}

	return nodes[0];
};

const getResponseHook = (dataset) => ({
  responseHook: (response) => {
    if (typeof response.data === 'string') {
      response.data = mustache.render(response.data, dataset);
    }
    return response;
  }
});

/**
 * вызывается с явной привязкой к контексту компонента
 * фигурирует mixin: DocMixin
 */
const getAsyncApiContext = function(isSwagger) {
  this.sourceRefresh().then(() => {
    const params =
      this.isTemplate
        ? getResponseHook(this.source.dataset)
        : undefined;

    requests.request(this.url, undefined, params)
      .then((response) => {
        if (isSwagger) {
          this.data = response.data;
          this.swaggerRender();
        } else {
          this.renderRefSection(response);
        }
      })
      .catch((e) => this.error = e)
      .finally(() => {
        if (!isSwagger && this.$refs?.asyncapi) {
          const html = this.$refs.asyncapi.shadowRoot.querySelector('style');
          html.innerHTML = asyncApiStyles;
        }
      });
  });
};

export {
	isObjectEmpty,
	warn,
	convertVNodeArray,
  getResponseHook,
  getAsyncApiContext
};
