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
      Navasardyan Suren, Sber

  Contributors:
      Navasardyan Suren, Sber - 2023
      R.Piontik <r.piontik@mail.ru> - 2024
      Alexander Romashin, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
const listeners = {};

const logger = getLoggerWithTag('i/i/gateway');

export default {
  initIdeaGateway() {
      window.$PAPI.gatewayCallback = (message) => {
        if (message?.data) {
          for (const action in message.data) {
            (listeners[action] || []).forEach((listener) => {
              logger.debug(() => `idea find and invoke listener ${action}`);
              listener(message.data[action]);
            });
          }
        }
      };
      logger.debug(() => 'idea window.$PAPI.gatewayCallback register');
  },

  initVsCodeGateway() {
    window.addEventListener('message', (event) => {
      const {command, content} = event?.data;
      if (['update-source-file', 'navigate'].includes(command)) {
        for (const action in content) {
          (listeners[action] || []).forEach((listener) => {
            logger.debug(() => `vscode find and invoke listener ${action}`);
            listener(content[action]);
          });
        }
      }
    });
    logger.debug(() => 'vscode window.addEventListener on \'message\' register');
  },
  appendListener(action, listener) {
    logger.debug(() => `gateway add listener for action ${action}`);
    const arr = listeners[action] = (listeners[action] || []);
    arr.push(listener);
  },
  removeListener(action, listener) {
    logger.debug(() => `gateway remove listener for action ${action}`);
    const arr = listeners[action] = (listeners[action] || []);
    const index = arr.indexOf(listener);
    if (index >= 0) arr.splice(index, 1);
  }
};
