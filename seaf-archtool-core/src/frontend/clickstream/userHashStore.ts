import {v4 as uuidv4} from 'uuid';
import {userIdentifiersStoreSeafPlugin} from '@front/clickstream/userIdentityStoreSeaf';
import env from '@front/helpers/env';
import userStore from '@front/store/userStore';

const USER_HASH_KEY = 'seaf_user_hash';
const FIFTY_YEARS_IN_MS = 1576800000000;

/**
 * Получение идентификатора (хеша) пользователя
 */
export const getUserHash = async(): Promise<string> => {
  if (env.isPlugin()) {
    return await __getUserHashPlugin();
  } else {
    return __getUserHashWeb();
  }
};

/**
 * Если мы запущены как web то хеш пользователя храним в localstorage
 */
function __getUserHashWeb(): string {
  let userHash = userStore.getUserData()?.userId;
  if (userHash) {
    return userHash;
  }
  userHash = localStorage.getItem(USER_HASH_KEY);
  if (userHash) {
    return userHash;
  }
  userHash = uuidv4();
  localStorage.setItem(USER_HASH_KEY, userHash);
  return userHash;
}

/**
 * Если мы запущены как plugin то хеш пользователя храним в хранилище плагина
 */
async function __getUserHashPlugin(): Promise<string> {
  let userHash = await userIdentifiersStoreSeafPlugin.getData(USER_HASH_KEY);
  if (!userHash) {
    userHash = uuidv4();
    await userIdentifiersStoreSeafPlugin.setData(USER_HASH_KEY, userHash, FIFTY_YEARS_IN_MS);
  }
  return userHash;
}
