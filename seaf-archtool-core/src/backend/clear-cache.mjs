import './helpers/env.mjs';

import path from 'path';
import fs from 'fs';
import {changeLoggerImpl, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {mainLogger} from '@back/utils/logger/constLoggers.mjs';
import {getPgPool} from "@back/drivers/postgres/pool.mjs";

const cacheMode = (process.env.VUE_APP_DOCHUB_DATALAKE_CACHE || 'none').toLocaleLowerCase();

changeLoggerImpl(mainLogger);
const logger = getLoggerWithTag('b/cache-clear.mjs');

switch (cacheMode) {
    case 'none':
    case 'memory':
    case 'redis': {
        const redisUnsupportedMessage = `redis cache now not supported, check env VUE_APP_DOCHUB_DATALAKE_CACHE, current value ${cacheMode}`;
        logger.error(() => redisUnsupportedMessage);
        throw Error(redisUnsupportedMessage);
    }
    case 'postgres': {
        const pgPool = getPgPool();
        logger.info(() => 'DROP TABLE IF EXISTS cache');
        await pgPool.query('DROP TABLE IF EXISTS cache');
        logger.info(() => 'DROP TABLE IF EXISTS ai_chat_session_data');
        await pgPool.query('DROP TABLE IF EXISTS ai_chat_session_data');
        logger.info(() => 'pgPool.end');
        await pgPool.end();
        break;
    }
    default: {
        const cacheDir = path.resolve(__dirname, '../../../', cacheMode);
        fs.readdir(cacheDir, (err, files) => {
            if (err) throw err;
            for (const file of files) {
                fs.unlink(`${cacheDir}/${file}`, err => logger.error(() => 'clearCache fs error', err));
            }
        });
    }
}

logger.info(() => 'full end');
