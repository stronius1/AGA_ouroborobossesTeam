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
*/

import mustache from 'mustache';

import datasets from '@front/helpers/datasets';
import requests from '@front/helpers/requests';
import uriTool from '@front/helpers/uri';
import env, {Plugins} from '@front/helpers/env';

function doUpload(content, mime) {
  const base64 = window.btoa(unescape(encodeURIComponent(content)));
  const href = `data:${mime};base64,${base64}`;
  if (env.isPlugin(Plugins.idea)) {
    window.$PAPI.download(
      href,
      'Выгрузка представления',
      'Выберите файл для сохранения'
    );
  } else {
    const link = document.createElement('a');
    document.body.appendChild(link);
    link.href = href;
    link.download = `dh_${Date.now()}.${mime.split('/').pop()}`;
    link.click();
  }
}

// Выгружает документы типа upload
//  id          - идентификатор документа
//  profile     - профиль документа
//  baseURI     - Базовый URI
//  params      - Параметры передаваемые в документ
//  manifest    - архитектурный манифест
export const uploadDocument = function(profile, path, params) {
  const provider = datasets();
  return new Promise((success, reject) => {
      if (profile.template) {
        const baseURI = uriTool.getBaseURIOfPath(`${path}/template`);
        requests.request(profile.template, baseURI, { raw: true }).then(({ data }) => {
          let content = data;
          provider.releaseData(path, params)
          .then((dataset) => {
            try {
              success(doUpload(mustache.render(content, dataset), profile.mimetype || 'text/plain'));
            } catch (e) {
              reject(e);
            }
          })
          .catch((e) => reject(e));
        }).catch((e) => reject(e));
      } else {
        provider.releaseData(path, params)
        .then((dataset) => {
          try {
            success(doUpload(JSON.stringify(dataset, null, 2), 'application/json'));
          } catch (e) {
            reject(e);
          }
        });
      }
  });
};
