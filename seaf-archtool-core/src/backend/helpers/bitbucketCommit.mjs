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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber

  Contributors:
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Alexander Romashin <romashin.a.va@sberbank.ru>, Sber - 2025
*/

import axios from 'axios';
import FormData from 'form-data';
import bitbucket from './bitbucket.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {parseAxiosBitbucketError} from '@back/helpers/axiosBitbucketErrorParser.mjs';
import { v4 as uuidv4 } from 'uuid';

const getRepositoryOptions = (bbPath) => {
    let rootPath = bbPath;
    if (!rootPath) {
        rootPath = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST;
    }
    const [protocol, projectID, repositoryID, source] = rootPath.split(':');
    const [branch] = source.split('@');
    const baseURL = process.env.VUE_APP_DOCHUB_BITBUCKET_URL;
    return {
        protocol,
        projectID,
        repositoryID,
        source,
        branch,
        baseURL: baseURL.endsWith('/') ? baseURL : `${baseURL}/`
    };
};

const checkItWasRequestWithoutChanges = (err) => {
    return (
        err?.response?.status === 409 &&
        err?.response?.data?.errors[0]?.message ===
        'The content provided is the same as what already exists. No change was committed.'
    );
};

const createBranch = async({newBranchName, repositoryOptions}) => {
    const result = {
        id: 0,
        stageName: 'Создание ветки',
        success: false
    };
    const {baseURL, projectID, repositoryID, branch} = repositoryOptions;
    result.message = `Создана ветка: ${newBranchName} от ветки ${branch} в репозитории ${repositoryID} в проекте ${projectID}`;
    const url = `${baseURL}rest/api/1.0/projects/${projectID}/repos/${repositoryID}/branches`;

    const body = {
        name: newBranchName,
        startPoint: `refs/heads/${branch}`
    };
    try {
        await axios({
            method: 'POST',
            url,
            data: body
        });
        result.success = true;
    } catch (err) {
        const axiosError = parseAxiosBitbucketError(err);
        result.message = `Ошибка при создании ветки: ${newBranchName}`;
        result.error = `${axiosError.status}: ${axiosError.statusText}: ${axiosError.message}`;
    }
    return result;

};

const updateFile = async({branch, fileName, content, repositoryOptions}) => {
    const {baseURL, projectID, repositoryID} = repositoryOptions;

    const url = `${baseURL}rest/api/1.0/projects/${projectID}/repos/${repositoryID}/browse/${fileName}`;

    const body = new FormData();
    body.append('branch', branch);
    body.append('sourceCommitId', 'HEAD');
    body.append('content', content);

    const headers = body.getHeaders();

    logger.debug(() => [
        `send request to bb [PUT] ${url}`,
        {title: 'branch', obj: branch},
        {title: 'sourceCommitId', obj: 'HEAD'},
        {title: 'content', obj: content}
    ]);

    try {
        return await axios({
            method: 'PUT',
            headers,
            url,
            data: body
        });
    } catch (err) {
        if (!checkItWasRequestWithoutChanges(err)) {
            throw err;
        }
    }
};

const createNewFile = async({branch, fileName, content, repositoryOptions}) => {
    const {baseURL, projectID, repositoryID} = repositoryOptions;

    const url = `${baseURL}rest/api/1.0/projects/${projectID}/repos/${repositoryID}/browse/${fileName}`;

    const body = new FormData();
    body.append('branch', branch);
    body.append('type', 'file');
    body.append('content', content);

    const headers = body.getHeaders();

    return await axios({
        method: 'PUT',
        headers,
        url,
        data: body
    });
};

const writeFile = async({branch, fileName, content, repositoryOptions}) => {
    const result = {
        success: false,
        path: fileName,
        mode: 'update',
        writeToBranch: branch
    };
    logger.debug(() => `try update file ${fileName} in branch ${branch}, with content [${JSON.stringify(content)}]`);
    try {
        await updateFile({branch, fileName, content, repositoryOptions});
        result.success = true;
        return result;
    } catch (err) {
        logger.debug(() => `updateFile ${fileName} get error`, err);
        if (err?.response?.status !== 404) {
            const axiosError = parseAxiosBitbucketError(err);
            result.message = `Ошибка при обновлении файла "${fileName}" в ветке "${branch}"`;
            result.error = `${axiosError.status}: ${axiosError.statusText}: ${axiosError.message}`;
            throw result;
        }
        // если статус 404, то ничего не делаем, попробуем создать файл
    }

    result.mode = 'create';
    logger.debug(() => `${fileName} not found in branch ${branch}, create new`);
    try {
        await createNewFile({branch, fileName, content, repositoryOptions});
        result.success = true;
        return result;
    } catch (err) {
        const axiosError = parseAxiosBitbucketError(err);
        logger.debug(() => [
            `createNewFile ${fileName} get error`,
            {title: 'axiosError', obj: axiosError}
        ]);
        result.message = `Ошибка при создании файла "${fileName}" в ветке "${branch}"`;
        result.error = `${axiosError.status}: ${axiosError.statusText}: ${axiosError.message}`;
        throw result;
    }
};

const writeFileWithDelay = async({branch, fileName, content, delay, repositoryOptions}) => {
    await new Promise(resolve => setTimeout(resolve, delay));
    return await writeFile({
        branch: branch,
        fileName: fileName,
        content: content,
        repositoryOptions: repositoryOptions
    });
};

const writeFileListWidthDelay = async({branchName, contentObject, repositoryOptions}) => {
    const DELAY = 300;
    let delayCounter = DELAY * -1;
    const dataList = Object.entries(contentObject);

    const result = {
        id: 1,
        stageName: 'Запись файлов',
        files: [],
        success: true
    };
    const promises = dataList.map(async([path, data]) => {
        delayCounter += DELAY;
        logger.debug(() => `create promise for write file with delay ${delayCounter}, path ${path}, data [${JSON.stringify(data)}]`);
        try {
            const fileResult = await writeFileWithDelay({
                branch: branchName,
                fileName: path,
                content: data,
                delay: delayCounter,
                repositoryOptions: repositoryOptions
            });
            result.files.push(fileResult);
        } catch (errorObject) {
            result.files.push(errorObject);
            result.success = false; // если хоть один файл не удалось загрузить - считаем шаг с ошибкой
            result.error = errorObject.error;
            result.message = errorObject.message;
        }
    });
    await Promise.all(promises);
    return result;
};

const createPR = async({fromBranch, repositoryOptions, userInfo}) => {
    const {baseURL, projectID, repositoryID, branch} = repositoryOptions;
    const result = {
        id: 2,
        stageName: `Создание pull request из ветки ${fromBranch} в ветку ${branch}`,
        success: false
    };

    const url = `${baseURL}rest/api/1.0/projects/${projectID}/repos/${repositoryID}/pull-requests`;

    let titlePostfix = '';
    if (userInfo?.name || userInfo?.id) {
        titlePostfix += ' from user:';
        if (userInfo?.name) {
            titlePostfix += ` ${userInfo.name}`;
        }
        if (userInfo?.id) {
            titlePostfix += ` (${userInfo.id})`;
        }
    }

    const body = {
        title: 'SEAF commit' + titlePostfix,
        // description: 'Описание для PR',
        closeSourceBranch: true,
        fromRef: {
            id: `refs/heads/${fromBranch}`
        },
        toRef: {
            id: `refs/heads/${branch}`
        }
    };

    try {
        const axiosResponse = await axios({
            method: 'POST',
            url,
            data: body
        });
        const data = axiosResponse.data;
        result.prId = data?.id;
        result.prVersion = data?.version;

        if (result.prId == null || result.prVersion == null) {
            logger.error(() => [
                'incorrect bitbucket answer for create pr',
                {title: 'answer.data', obj: data}
            ]);
            throw new Error('Bitbucket return incorrect answer');
        }

        result.message = `Создан PR #${result.prId}`;
        result.success = true;
        return result;
    } catch (err) {
        const axiosError = parseAxiosBitbucketError(err);
        result.message = `Ошибка при создании pull-request ("${fromBranch}" ~> "${branch}")`;
        result.error = `${axiosError.status}: ${axiosError.statusText}: ${axiosError.message}`;
        return result;
    }
};

const mergePR = async({prId, version, repositoryOptions}) => {

    const result = {
        id: 3,
        stageName: `Слияние pull request #${prId}`,
        success: false
    };
    const {baseURL, projectID, repositoryID} = repositoryOptions;

    const url = `${baseURL}rest/api/1.0/projects/${projectID}/repos/${repositoryID}/pull-requests/${prId}/merge`;

    const body = {
        version
    };

    try {
        await axios({
            method: 'POST',
            url,
            data: body
        });
        result.message = 'PR успешно влит';
        result.success = true;
    } catch (err) {
        const axiosError = parseAxiosBitbucketError(err);
        result.message = `Merge-request #${prId} завершился с ошибкой`;
        result.error = `${axiosError.status}: ${axiosError.statusText}: ${axiosError.message}`;
    }
    return result;
};

const logger = getLoggerWithTag('bb-commit');

const commitToBitbucketApiV1 = async({content, bbRootPath, userInfo}) => {
    const result = {
        success: false,
        stack: []
    };

    try {
        const newBranchName = `commit/${Date.now()}`;
        const repositoryOptions = getRepositoryOptions(bbRootPath);
        const createBranchResult = await createBranch({newBranchName: newBranchName, repositoryOptions: repositoryOptions});
        result.stack.push(createBranchResult);
        if (!createBranchResult.success) {
            const {message, error} = createBranchResult;
            return Object.assign(result, {message, error});
        }

        const writeFilesResult = await writeFileListWidthDelay({
            branchName: newBranchName,
            contentObject: content,
            repositoryOptions: repositoryOptions
        });
        result.stack.push(writeFilesResult);
        if (!writeFilesResult.success) {
            logger.debug(() => [
                'error when save file in bb',
                {title: 'result.writeFiles', obj: writeFilesResult}
            ]);
            const {message, error} = writeFilesResult;
            return Object.assign(result, {message, error});
        }

        const pullRequestResult = await createPR({
            fromBranch: newBranchName,
            repositoryOptions: repositoryOptions,
            userInfo
        });
        result.stack.push(pullRequestResult);
        if (!pullRequestResult.success) {
            const {message, error} = pullRequestResult;
            return Object.assign(result, {message, error});
        }

        const { prId, prVersion } =  pullRequestResult;

        const mergeRequestResult = await mergePR({
            prId: prId,
            version: prVersion,
            repositoryOptions: repositoryOptions
        });
        result.stack.push(mergeRequestResult);
        if (!mergeRequestResult.success) {
            const {message, error} = mergeRequestResult;
            Object.assign(result, {message, error});
        }
        result.success = mergeRequestResult.success; // процесс успешно завершен, если последний шаг успешный
    } catch (err) {
        const traceId = uuidv4();
        logger.error(() => `${traceId}: Error when put-content, state = ${result}`, err);
        result.success = false;
        result.message = `Непредвиденная ошибка: ${traceId}`;
        result.error = err.message;
    }
    return result;
};

const commitToBitbucketApiV2 = async({content}) => {
    const result = {
        success: false,
        createBranch: null,
        writeFiles: null,
        createPR: null,
        mergePR: null
    };
    const {projectID, repositoryID, branch} = getRepositoryOptions();

    const requestUri = bitbucket.makeSourceURI(projectID, repositoryID);

    const data = new URLSearchParams();
    data.append('branch', branch);

    for (let url in content) {
        data.append(url, content[url]);
    }

    try {
        await axios({
            method: 'POST',
            url: requestUri.toString(),
            data
        });
        result.success = true;
    } catch (err) {
        const traceId = uuidv4();
        logger.error(() => `${traceId}: error when put content with bb v2`, err);
        const axiosError = parseAxiosBitbucketError(err);
        result.message = `Непредвиденная ошибка: ${traceId}`;
        result.error = axiosError.message;
        result.success = false;
    }
    return result;
};

/**
 *
 * @param  {content: object, bbRootPath: string, userInfo?: {id: string, name: string}} data - The latitude and longitude.
 */
export const commitToBitbucket = (data) => {
    let writeMode = process.env.VUE_APP_DOCHUB_BITBUCKET_WRITE_MODE;
    if (!writeMode) {
        writeMode = process.env.VUE_APP_DOCHUB_BITBUCKET_MODE; // по дефолту берем режим чтения, чтобы работало у тех кто не испольузет адаптер
    }
    switch (writeMode) {
        case 'v1':
            return commitToBitbucketApiV1(data);
        case 'v2':
            return commitToBitbucketApiV2(data);
        default:
            throw Error('Некорректно указано значение VUE_APP_DOCHUB_BITBUCKET_WRITE_MODE');
    }
};
