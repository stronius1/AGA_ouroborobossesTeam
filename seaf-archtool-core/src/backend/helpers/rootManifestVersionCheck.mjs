export function validateRootManifest(rootJson) {
    if (!rootJson) {
        throw Error('root manifest object not exist (undefined or null)');
    }
    let imports = rootJson.imports;
    if (!imports) {
        throw Error('root manifest not contains \'imports\' directive');
    }
    if(!Array.isArray(imports)) {
        throw Error('root manifest \'imports\' directive not array, but must be');
    }
    if(typeof imports[0] !== 'object') {
        throw Error('root manifest \'imports\' directive is not an object, but must be object with params \'root\' and \'permission\'.');
    }
    let errors = [];
    for(let imp in imports) {
        const importForCheck = imports[imp];
        if (!importForCheck.root) {
            errors.push(`Error in root manifest: imports[${imp}] must have 'root' property, which direct on domain root manifest`);
        }
        if (!importForCheck.permission) {
            errors.push(`Error in root manifest: imports[${imp}] must have 'permission' property, which direct access permission for data`);
        }
        if (!importForCheck.alias) {
            errors.push(`Error in root manifest: imports[${imp}] must have 'alias' property, which direct alias for reload data (used for reload request)`);
        }

        if (importForCheck.repos) {
            const repoErrors = checkRepos(importForCheck.repos);
            for (const error of repoErrors) {
                errors.push(`Error in root manifest: imports[${imp}] have error in repos array: ${error}`);
            }
        }
    }
    if (errors.length > 0) {
        throw Error(errors.join('; '));
    }
}

/**
 * проверка, что repos это массив, что его элементы имеют обязательные атрибуты type и url с типом string
 * @param repos
 * @returns {string[]|*[]}
 */
function checkRepos(repos) {
    if (!Array.isArray(repos)) {
        return ['repos must be array of object ({type: string, url: string})'];
    }
    if (repos.length === 0) {
        return [];
    }
    const errors = [];
    for (let i = 0; i < repos.length; i++) {
        const repo = repos[i];
        if (!repo.type || typeof repo.type !== 'string') {
            errors.push(`repo [${i}] have incorrect 'type' value (not exist or not string)`);
        }
        if (!repo.url || typeof repo.url !== 'string') {
            errors.push(`repo [${i}] have incorrect 'url' value (not exist or not string)`);
        }
    }
    return errors;
}
