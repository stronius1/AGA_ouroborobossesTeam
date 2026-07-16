import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { v4 as uuidv4 } from 'uuid';
import {HttpHeaders} from '@global/helpers/httpHeaders.mjs';

const LOG_TAG = 'cluster';
const logger = getLoggerWithTag(LOG_TAG);

const REQ_MODE_PERMISSION = 'permission';
const REQ_MODE_ALIAS = 'alias';

/**
 * @template {string[]} T - массив строк (или пустой массив)
 */
class AliasParseResult {
    constructor(data, error) {
        this.data = data;
        this.error = error;
    }
    /**
     * Создать успешный результат
     * @param {T} data - массив строк (может быть пустым)
     * @returns {AliasParseResult<[]>}
     */
    static ok(data) { return new AliasParseResult(data, null); }

    /**
     * Создать результат с ошибкой
     * @param {string} error - сообщение об ошибке
     * @returns {AliasParseResult<[]>}
     */
    static fail(error) { return new AliasParseResult(null, error); }
}

/**
 * Парсим alias данные из запроса
 * В запросе могут быть переданы как alias так и permission - режим определяется параметром mode.
 * mode может быть permission или alias, alias используется по дефолту
 * Параметр alias проверяется на тип (должна быть строка или массив строк), если значения есть. Если значения не переданы,
 * тогда возвращается пустой массив как результат
 *
 * Если mode указан как permission, тогда заменяем переданные alias (в которых должен быть список permission) на сами alias из rootManifest
 * @param traceId - traceId для логов
 * @param req - http запрос
 * @param rootManifest - root манифест текущего состояния
 * @returns AliasParseResult - содержит результат в виде массива в атрибуте data или текст ошибки в атрибуте error
 */
function parseAliasFromReq(traceId, req, rootManifest) {
    let aliasListRaw = req.query.alias;
    if (!aliasListRaw) {
        return AliasParseResult.ok([]);
    }
    const aliasTypeOf = typeof aliasListRaw;
    if (!Array.isArray(aliasListRaw) && aliasTypeOf !== 'string') {
        return AliasParseResult.fail('Bad params \'alias\', must not send or must be string (maybe multiple param)');
    }
    aliasListRaw = typeof aliasListRaw === 'string' ? [aliasListRaw] : aliasListRaw; // переводим значение в массив
    let mode = req.query.mode || REQ_MODE_ALIAS;
    if (mode === REQ_MODE_ALIAS) {
        return AliasParseResult.ok(aliasListRaw);
    } else if (mode === REQ_MODE_PERMISSION) {
        const aliasResult = [];
        for (const permission of aliasListRaw) {
            let importFromRoot = rootManifest.imports.find(el => el.permission === permission);
            if (importFromRoot) {
                aliasResult.push(importFromRoot.alias);
            } else {
                logger.debug(() => `${traceId}: permission ${permission} not found in root manifest, skip for update`);
            }
        }
        return AliasParseResult.ok(aliasResult);
    } else {
        return AliasParseResult.fail(`Bad args 'mode', allow '${REQ_MODE_PERMISSION}' or '${REQ_MODE_ALIAS}'(default)`);
    }
}

function parseAliasesFromRootManifest(rootManifest) {
    return rootManifest.imports.map(el => el.alias);
}

export default (app, clusterCache) => {

    // дубль обработчика из core.mjs, тот работает для режима backend, этот в режиме кластера
    app.put(['/seaf-core/api/core/storage/reload', '/core/storage/reload'], async function(req, res) {
        const traceId = uuidv4();
        logger.debug(() => `${traceId}: accept req`);
        try {
            const reloadSecret = req.query.secret;
            if (reloadSecret !== process.env.VUE_APP_DOCHUB_RELOAD_SECRET) {
                res.status(403).json({
                    error: `${traceId}: Error reload secret is not valid [${reloadSecret}]`
                });
                return;
            }
            let rootManifest = await clusterCache.getRootManifestData();
            if (!rootManifest) { // подумать, раньше тут было 500 и заголовок retry after может заголовок надо вернуть
                res.status(500)
                    .set(HttpHeaders.RETRY_AFTER, '60') // Попробуй через 60 секунд
                    .json({
                        error: `${traceId}: server not ready (aliases empty in storage)`
                    });
                return;
            }
            if (req.query.reloadRoot === 'true') {
                // если передан параметр reloadRoot со значением true, то запускаем перезагрузку без изменения таймингов,
                // чтобы найти новые репозитории в root манифесте или удалить старые
                logger.debug(() => `${traceId}: 'reloadRoot' param is true, just set reload command`);
                await clusterCache.setCommand('manifest_reload');
                res.status(200).json({});
                return;
            }

            // в запросе может быть передан 0 или больше параметров alias, собираем их в массив
            const parseAliasesResult = parseAliasFromReq(traceId, req, rootManifest);
            if (parseAliasesResult.error) {
                res.status(400).json({
                    error: `${traceId}: ${parseAliasesResult.error}`
                });
                return;
            }
            const aliases = parseAliasesResult.data;
            const manifestAliases = parseAliasesFromRootManifest(rootManifest);
            logger.debug(() => `${traceId}: aliases = ${aliases}`);
            if (aliases.length === 0) {
                logger.debug(() => `${traceId}: no alias send, then update all`);
                for (const manifest of manifestAliases) {
                    logger.trace(() => `${traceId}: processing with element ${manifest}`);
                    await clusterCache.setExpectTimeManifest(manifest);
                }
            } else {
                logger.debug(() => `${traceId}: reload by alias array`);
                let filteredAliases = aliases.filter(el => manifestAliases.includes(el));
                if (filteredAliases.length === 0) {
                    logger.debug(() => `${traceId}: no any alias find in manifest state`);
                    res.status(400).json({
                        error: `${traceId}: bad params 'alias' (nir)` // not in root - значит, что мы не нашли подходящий imports.alias соответсвующий тем, что переданы в запросе в root манифесте
                    });
                    return;
                }
                logger.debug(() => `${traceId}: alias after filter ${filteredAliases}`);
                for (const manifest of filteredAliases) {
                    logger.debug(() => `${traceId}: processing array element ${manifest}`);
                    await clusterCache.setExpectTimeManifest(manifest);
                }
            }
            await clusterCache.setCommand('manifest_reload');
            logger.debug(() => `${traceId}: finish`);
            res.status(200).json({
                message: 'success'
            });
        } catch (error) {
            logger.error(() => `${traceId}: error when process request`, error);
            res.status(500).json({
                error: `${traceId}: error when process request`
            });
        }
    });
};
