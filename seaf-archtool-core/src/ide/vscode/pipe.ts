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
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2024
*/

import { v4 as uuidv4 } from 'uuid';
import md5 from 'md5';

import plantuml from '@front/helpers/plantuml';
import { PrepareHTMLForPrint } from '@front/helpers/html';
import {papiSettingUpdated} from '@ide/papiLifeCycle';
import gateway from '@ide/gateway';

const emit = (command: string, content: any): Promise<any> | void =>
  vscode.postMessage({ command, content });

export const listeners: { [key: string]: any } = {};

export default (): void => {
  gateway.initVsCodeGateway();
  window.$PAPI = {
    settings: window.DochubVsCodeExt.settings,
    checkIsRootManifest(): void {
      emit('check-is-root-manifest', '');
    },
    pluginList(plugins) {
      emit('pluginList', plugins);
    },
    loaded() {
      emit('loaded', '');
    },
    initProject(mode): void {
      emit('create', mode);
    },
    print() {
      emit('print', { document: PrepareHTMLForPrint() });
    },
    addLinks(node): void {
      emit('addLinks', node);
    },
    applyEntitiesSchema(schema) {
      emit('applyschema', JSON.stringify({ schema }));
    },
    debug() {
      emit('debug', undefined);
    },
    download(content, title, description, extension, fileName = `dh_${Date.now()}`): void {
      const stringifedUri = JSON.stringify({
        content, title, description, extension, fileName
      });

      emit('download', stringifedUri);
    },
    upload(): Promise<void> {
      const uuid = uuidv4();

      emit('upload', {
        uuid
      });

      return new Promise((res, rej): void => {
        listeners[uuid] = { res, rej };
      });
    },
    goto(source, entity, id): void {
      emit('goto', JSON.stringify({ source, entity, id }));
    },
    reload(currentRoute): void {
      emit('reload-force', { currentRoute });
    },
    renderPlantUML(uml): Promise<void> {
      const stringifedUri = JSON.stringify(plantuml.svgURL(uml));
      const uuid = uuidv4();

      emit('plantuml', {
        stringifedUri,
        uuid
      });

      return new Promise((res, rej): void => {
        listeners[uuid] = { res, rej };
      });
    },
    invalidateCache() {
      emit('invalidateCache', null);
    },
    clearDatasetsCache(datasetsIDs: string[]) {
      const datasetCacheKeys = datasetsIDs.map(id => md5(`{"path":"/datasets/${id}"}`));
      emit('clearCaches', { datasetCacheKeys });
    },
    updateCache(key: string, data: any) {
      emit('updateCache', { key, data: JSON.stringify(data) });
    },
    pullFromCache(key: string, resolver: () => void, args: object): Promise<void> {
      const uuid = uuidv4();

      emit('pullFromCache', { uuid, key: md5(key) });

      return new Promise((res, rej): void => {
        listeners[uuid] = { res, rej, resolver, args };
      });
    },
    request(uri): Promise<void> {
      const stringifedUri = JSON.stringify(uri);
      const uuid = uuidv4();

      emit('request', {
        stringifedUri,
        uuid
      });

      return new Promise((res, rej): void => {
        listeners[uuid] = { res, rej };
      });
    },
    pushFile(fullPath, content): Promise<void> {
      const url = new URL(fullPath);
      const uri = { raw: false, url };
      const stringifedUri = JSON.stringify(uri);

      const arrayBuffer = new TextEncoder().encode(content);
      const uint8Array = new Uint8Array(arrayBuffer);

      const uuid = uuidv4();

      emit('push-file', {
        stringifedUri,
        uuid,
        value: uint8Array
      });

      return new Promise((res, rej): void => {
        listeners[uuid] = { res, rej };
      });
    }
  };
};

//Событие обновления настроек кидаем только если запущены в vscode о чем нам говорит наличие DochubVsCodeExt
if (window.DochubVsCodeExt) {
  papiSettingUpdated();
}
