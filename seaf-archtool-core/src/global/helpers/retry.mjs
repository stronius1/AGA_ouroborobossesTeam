import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {v4 as uuidv4} from 'uuid';

const logger = getLoggerWithTag('retry_func');

export async function execWithRetry(retryCount = 0, pauseBetweenAttemptMs = 0, fn) {
    let lastError;
    let logUuid = '';
    for (let attempt = 0; attempt <= retryCount; attempt++) {
        logger.trace(() => `${logUuid}: Attempt ${attempt + 1}`);
        try {
            const result = await fn();
            if (attempt !== 0) {
                logger.debug(() => `${logUuid}: Attempt ${attempt + 1} success`);
            }
            return result;
        } catch (error) {
            if (logUuid === '') {
                logUuid = uuidv4(); // генерим 1 раз только если возникла ошибка
            }
            lastError = error;
            if (attempt < retryCount) {
                logger.debug(() => `${logUuid}: Attempt ${attempt + 1} failed with error: ${error?.message}, wait ${pauseBetweenAttemptMs} ms and trying again...`);
                await new Promise(resolve => setTimeout(resolve, pauseBetweenAttemptMs));
            }
        }
    }

    throw lastError || new Error(`${logUuid}: All attempt failed`);
}
