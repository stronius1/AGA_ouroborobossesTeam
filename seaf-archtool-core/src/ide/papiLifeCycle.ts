import {getLoggerWithTag} from '@global/logger/v2/logger';

let papiSettingUpdate: PapiCallback[] = [];

const logger = getLoggerWithTag('papiLifeCycle');

interface PapiCallback {
    funcName: string,
    func: () => void;
}

export function addPapiSettingUpdateCallbacks(callback: any) {
    const validateResult = _validateCallback(callback);
    if (!validateResult.isValid) {
        logger.error(() => `Ошибка при регистрации callback функции ${validateResult.error} для addPapiSettingUpdateCallbacks`, new Error());
        return;
    }
    if (window.$PAPI?.ideSettings) {
        callback.func();
    } else {
        papiSettingUpdate = papiSettingUpdate.filter(el => el.funcName !== callback.funcName);
        papiSettingUpdate.push(callback);
    }
}

export function papiSettingUpdated() {
    papiSettingUpdate.forEach(cb => {
        try {
            cb.func();
        } catch (e) {
            logger.error(() => `error when exec callback with name: ${cb.funcName}`, e);
        }
    });
}

function _validateCallback(item: any): { isValid: boolean; error?: string } {
    if (item === null) return { isValid: false, error: 'callback is null' };
    if (typeof item !== 'object') return { isValid: false, error: 'callback is not an object' };
    if (typeof item.funcName !== 'string') return { isValid: false, error: 'callback.name is not a string' };
    if (typeof item.func !== 'function') return { isValid: false, error: 'callback.func is not a function' };
    return { isValid: true };
}
