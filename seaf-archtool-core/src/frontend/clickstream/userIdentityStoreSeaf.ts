import {UserIdentifiersStore} from '@sbol/clickstream-agent/src/lib/store/user-identifiers-store';

/**
 * Функционал для сохранения данных пользователя кликстрима в плагинах
 */
export const userIdentifiersStoreSeafPlugin : UserIdentifiersStore = {

  async getData(name: string): Promise<string | undefined> {
    const clickstreamData = await window.$PAPI.getClickstreamData(name);
    return clickstreamData?.value;
  },

  async setData(name: string, value: string, ms: number): Promise<void> {
    window.$PAPI.setClickstreamData(name, value, ms);
  },

  async deleteData(name: string): Promise<void> {
    window.$PAPI.deleteClickstreamData(name);
  }
};
