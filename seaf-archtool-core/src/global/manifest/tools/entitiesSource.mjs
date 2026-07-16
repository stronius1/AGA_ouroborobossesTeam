import parser from '@global/manifest/parser3/index.mjs';
import yaml from 'yaml';

/**
 * Prepares entities data by merging provided entity values with data fetched from their source files.
 *
 * Iterates through entities grouped by schema, retrieves source file information from `sourceMap`,
 * fetches data from the LAST source file for each entity, merges the provided entity data,
 * and returns a map of source file paths to their updated content as strings.
 *
 * @param {Object} entities - A nested object of entities, structured as `{ [schema: string]: { [entKey: string]: entityValue: Object } }`. The function will only overwrite and add properties, will not delete existing ones.
 * @param {Function} request - A function that accepts a source URL/path as a string and returns a promise resolving to an object containing a `data` property with the parsed content (e.g., `{ data: {...} }`).
 * @param {Function} logger - A logger function.
 * @param {Object} [options] - An options object with the following properties:
 *   @property {string} [options.defaultSource] - A fallback source path for new entities that are not yet present in the existing architecture. If specified, it will be used as the first (and potentially only) source for new entities.
 *   @property {string} [options.baseURI] - A base URI to be prepended to source paths when fetching data via the `request` function.
 * @param {Record<string, { sources: string[] }>} [sourceMap=parser.sourceMap] - A source map from the manifest parser. If not provided, the sourceMap of the global parser object is used instead.
 * @returns {Promise<Object<string, string>>} A promise resolving to an object where keys are source file paths (with `@` prefix if from Bitbucket) and values are stringified JSON or YAML content.
 * @throws {Error} If `sourceMap` is missing or falsy.
 * @throws {Error} If `request` is not a function.
 */
export async function prepareEntitiesData(entities, request, logger, options, sourceMap = parser.sourceMap) {
    if (!sourceMap) {
        throw new Error('No source map could be established for the request to prepareEntitiesData');
    }
    if (typeof request !== 'function' || !logger) {
        throw new Error('request and logger are required in prepareEntitiesData');
    }
    const fileData = {};
    for (const [schema, schemaEntities] of Object.entries(entities)) {
        for (const [entKey, entValue] of Object.entries(schemaEntities)) {
            const key = `/${schema}/${entKey}`;
            const keySources = sourceMap[key]?.sources ?? [];
            const sources = [];
            if (options?.defaultSource) {
                sources.push(options.defaultSource);
            }
            sources.push(...keySources);
            if (!sources?.length) {
                logger.debug(() => `No sources received for entity ${entKey}`);
                continue;
            }
            // If the entity is described in several files, we take the last source file, because we need to choose one, might as well be the last one.
            const lastSource = sources[sources.length - 1];
            let data = fileData[lastSource];
            // If no fetch happened for this source, fetch it now.
            if (!data) {
                const requestData = await request(lastSource, options?.baseURI).catch((err) => {
                    // If there's no file, we might need to create it.
                    if (err?.response?.status === 404) {
                        return { data: null };
                    } else {
                        logger.warn(() => `Error while fetching data during preparation of entity ${entKey} for saving:`, err);
                    }
                });
                // If an error occurred, we already logged it.
                if (!requestData) {
                    continue;
                }
                if (!requestData.data) {
                    // If no data received for default source, either file doesn't exist or it's empty. Substitute with empty object.
                    if (options?.defaultSource === lastSource) {
                        fileData[lastSource] = data = {
                            [schema]: {
                                [entKey]: {}
                            }
                        };
                    } else {
                        logger.debug(`Expected entities data, but no data received for source ${lastSource}`);
                        continue;
                    }
                } else {
                    fileData[lastSource] = data = requestData.data;
                }
            }
            if (!data?.[schema]) {
                // Weird case, but you never know.
                logger.warn(() => `According to the source map, schema ${schema} was expected in source ${lastSource}, but it is missing from the received data.`);
                continue;
            }
            if (!data[schema][entKey]) {
                // If it's default source, the entity might be missing. Add it.
                data[schema][entKey] = entValue;
            } else {
                Object.assign(data[schema][entKey], entValue);
            }
        }
    }
    const output = {};
    for (const [source, data] of Object.entries(fileData)) {
        let dataString;
        if (source.endsWith('.json')) {
            dataString = JSON.stringify(data);
        } else if (source.endsWith('.yaml')) {
            dataString = yaml.stringify(data);
        }
        // Currently, put-content endpoint handler expects paths with `@` prefix for Bitbucket sources, however, the parser writes sources without it.
        const outputKey = source.startsWith('bitbucket:') ? '@' + source : source;
        output[outputKey] = dataString;
    }
    return output;
}
