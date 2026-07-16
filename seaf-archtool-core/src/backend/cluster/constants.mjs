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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

export const NodeStatus = Object.freeze({
    MASTER: 0,
    WAIT: 1,
    SLAVE: 2,
    NO_MANIFEST: 3,
    RELOAD: 4,
    NOT_CONNECTED_TO_CACHE: 5
});

export const CLUSTER_MASTER_COMMAND = 'SEAF.master.command';
export const CLUSTER_MASTER_COMMAND_STATE = 'SEAF.master.state';
export const CLUSTER_ROOT_MANIFEST_DATA = 'SEAF.root.manifest';
export const CLUSTER_MANIFEST = 'SEAF.manifest__';
export const CLUSTER_CACHE_PREFIX = 'SEAF.cache.';
export const CLUSTER_MANIFEST_UPDATE_TIME_KEY = 'SEAF.manifest.expected.ts__';
export const CLUSTER_ALL_MANIFEST_ACTUAL_TIME_KEY = 'SEAF.manifest.actual.ts';
export const CLUSTER_COMMAND_REFRESH_TIMESTAMP = 'SEAF.command.refreshTimestamp';
export const CLUSTER_MANIFEST_PARSER = 'SEAF.manifest.parser__';
export const CLUSTER_MANIFEST_META = 'SEAF.manifest.meta__';
export const CLUSTER_MASTER_INFO = 'SEAF.master';
export const CLUSTER_MASTER_INFO_PROBE = 'SEAF.master.info-probe.';

/**
 * Право, которое используется как placeholder если ролевая модель v2 выключена.
 * Чтобы не ломать процесс работы с несколькими манифестами, один единый манифест будем сохранять под этим правом
 * @type {string}
 */
export const DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2 = '__disabled_roles_v2';
export const DEFAULT_ACCESS_WITHOUT_ROLE_MODEL_V2 = 'repo_admin';
