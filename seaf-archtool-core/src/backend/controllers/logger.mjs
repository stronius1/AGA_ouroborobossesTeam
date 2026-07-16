/*
  Copyright (C) 2023 Sber

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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2024
*/


import {mainLogger} from '@back/utils/logger/constLoggers.mjs';

export default (app) => {
    app.put(['/seaf-core/api/logger/update-level', '/logger/update-level'], (req, res) => {
        const secret = req.query.secret;
        if (secret !== process.env.VUE_APP_DOCHUB_RELOAD_SECRET) {
            res.status(403).send({
                error: `Error: reload secret is not valid [${secret}]`
            });
        } else {
            const result = mainLogger.setLevel(req.query.level);
            res.status(result ? 200 : 400).send(result);
        }
    });
    app.get(['/seaf-core/api/logger/level', '/logger/level'], (req, res) => {
        const secret = req.query.secret;
        if (secret !== process.env.VUE_APP_DOCHUB_RELOAD_SECRET) {
            res.status(403).send({
                error: `Error: reload secret is not valid [${secret}]`
            });
        } else {
            res.status(200).send({
                level: mainLogger.getLevelName()
            });
        }
    });
};
