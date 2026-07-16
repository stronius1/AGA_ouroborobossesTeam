/*
  Copyright (C) 2026 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {getPermissionWithAccess} from '@back/utils/get-user-permission.mjs';
import {getImportByAlias} from '@back/storage/manifestHolder.mjs';
import helpers from '@back/controllers/helpers.mjs';

const logger = getLoggerWithTag('b/c/c/user-rights.controller');

export default (app) => {

    app.get('/seaf-core/api/core/about-alias', async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        
        const alias = req.query.alias;
        if (!alias) {
            res.status(400).json({
                error: 'Required request param \'alias\' missing'
            });
            return;
        }

        const importByAlias = getImportByAlias(alias);
        if (!importByAlias) {
            res.status(400).json({
                error: 'data by alias not found or not permitted (nf)'
            });
            return;
        }

        try {
            let permissions = getPermissionWithAccess(req);
            if (!Array.isArray(permissions)) {
                permissions = [permissions];
            }
            const dataAboutAlias = permissions.some(el => el?.rp === importByAlias.permission);
            if (!dataAboutAlias) {
                res.status(400).json({
                    error: 'data by alias not found or not permitted (np)'
                });
                return;
            }

            res.status(200).json(importByAlias);
        } catch (error) {
            logger.error(() => 'error when process request', error);
            res.status(500).json({
                error: 'error when process request'
            });
        }
    });
};
