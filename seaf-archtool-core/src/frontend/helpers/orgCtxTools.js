import env from '@front/helpers/env';
import consts from '@front/consts.js';

/**
 * Проверить, что переданный url это адрес backend сервиса, а не какой-то внешней системы
 * Если в окружении backendURL не задан то проверки не будет вернется false
 * @param url - адрес для проверки
 * @returns {boolean} - true если хост параметра совпадает с хостом backendURL
 *                      false если не совпадает или backendURL не задан
 */
export function isUriHostEqualBackendHost(url) {
    if (!env.backendURL) {
        return false;
    }
    const urlHost = (new URL(url)).host;
    // backendHost нельзя вынести в константу т.к. при первом обращении переменных окружения еще нет и сохраняется адрес из браузера
    const backendHost = (new URL(env.backendURL)).host;
    return urlHost === backendHost;
}

/**
 * Получить контекст организации/архитектуры/orgctx из адресной строки браузера
 * @returns {string|null|undefined} - контекст при наличии
 */
export function extreactOrgCtxFromWindow() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(consts.roleModelV2.urlAliasParamName);
}
