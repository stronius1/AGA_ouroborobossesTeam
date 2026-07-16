import { createRepositoryIDfromURI } from '@global/manifest/parser3/helpers.mjs';
import { checkIsAbsoluteBitbucketPath } from './checkIsAbsoluteBitbucketPath.mjs';
import { HttpError } from './httpError.mjs';
import { Parser } from '@global/manifest/parser3/index.mjs';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import cache from '@back/storage/cache.mjs';
import {
    CLUSTER_COMMAND_REFRESH_TIMESTAMP,
    CLUSTER_MANIFEST,
    CLUSTER_MANIFEST_PARSER
} from '@back/cluster/constants.mjs';

import YAML from 'yaml';
import objectHash from 'object-hash';

const logger = getLoggerWithTag('/b/h/putContent');

const normalizePathToFile = (path) => {
  const CURRENT = '.';
  const BACK = '..';
  const PATH_SEPARATOR = '/';

  const splitedPath = path.split(PATH_SEPARATOR);

  let normalizedSlicedPath = [];

  for (let i = 0; i < splitedPath.length; i++) {
    const dir = splitedPath[i];
    switch (dir) {
      case BACK:
        normalizedSlicedPath = normalizedSlicedPath.slice(0, -1);
        break;
      case CURRENT:
      case '':
        break;
      default:
        normalizedSlicedPath.push(dir);
    }
  }
  return normalizedSlicedPath.join(PATH_SEPARATOR);
};

const normalizePathsInContent = (content, baseDir) => {
  const contentWithNormalizedPaths = {};

  const appRootManifestRepositoryPath = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST.split('@')[0];

  for (let userSpecifiedUri in content) {
    let path;
    if (checkIsAbsoluteBitbucketPath(userSpecifiedUri)) {
      path = userSpecifiedUri.slice(1);
    } else {
      const pathToFile = baseDir ? `${baseDir}/${userSpecifiedUri}` : userSpecifiedUri;
      path = `${appRootManifestRepositoryPath}@${pathToFile}`;
    }

    const [repositoryInfo, filePath] = path.split('@');

    const normalizedFilePath = normalizePathToFile(filePath);
    const normalizedUri = `${repositoryInfo}@${normalizedFilePath}`;

    contentWithNormalizedPaths[normalizedUri] = content[userSpecifiedUri];
  }

  return contentWithNormalizedPaths;
};

const checkThatAllPathsReferToSameRepository = (pathList) => {
  const uniqueRepositories = new Set(pathList.map((path) => path.split('@')[0]));
  return uniqueRepositories.size === 1;
};

const checkThatAllPathsUsedInManifest = (pathList, repositorySources = []) => {
  const unconnectedRepositories = pathList.filter((path) => {
    const repositoryID = createRepositoryIDfromURI(path);
    return !repositorySources.includes(repositoryID);
  });
  return unconnectedRepositories.length === 0;
};

const parseContent = (url, content) => {
  if (url.endsWith('.yaml')) {
    return YAML.parse(content);
  } else if (url.endsWith('.json')) {
    return JSON.parse(content);
  } else {
    throw new HttpError('Не удалось обработать файл. Допустимые форматы: "yaml", "json".', 400);
  }
};

export const validateAndFormatContent = (content, storage, hash) => {
  if (storage._joinManifest) {
    throw new HttpError('Сохранение данных не доступно если у пользователя есть права на несколько организаций', 400);
  }

  if (!(content && typeof content === 'object' && !Array.isArray(content))) {
    throw new HttpError(
      'Отсутствует тело запроса, или нет обязательного атрибута content, или он не json объект (не массив)',
      400
    );
  }

  let baseDir = storage?.md5Map?.[hash];
  if (baseDir) {
    baseDir = baseDir.split('@')[1].split('/').slice(0, -1).join('/');
  }

  const contentWIthNormalizedPaths = normalizePathsInContent(content, baseDir);

  const pathList = Object.keys(contentWIthNormalizedPaths);

  const isAllPathHasSameRepositoryInfo = checkThatAllPathsReferToSameRepository(pathList);
  if (!isAllPathHasSameRepositoryInfo) {
    throw new HttpError('Производимые изменения должны осуществляться в одном репозитории', 400);
  }

  const isAllPathConnectedToManifest = checkThatAllPathsUsedInManifest(pathList, storage?.repositorySources);
  if (!isAllPathConnectedToManifest) {
    throw new HttpError('Репозиторий изменяемого файла должен быть подключен к манифесту', 400);
  }

  return contentWIthNormalizedPaths;
};

export const createBitbucketCommitData = (validatedAndFormatedContent) => {
  const dataToCommit = {};
  let bbRootPath;
  for (let path in validatedAndFormatedContent) {
    const [repositoryInfo, pathToFile] = path.split('@');
    dataToCommit[pathToFile] = validatedAndFormatedContent[path];

    if (!bbRootPath) {
      bbRootPath = repositoryInfo;
    }
  }

  return {
    bbRootPath,
    content: dataToCommit
  };
};

export const createLayerUpdateDataByParser = (validatedAndFormatedContent) => {
  return Object.keys(validatedAndFormatedContent).map((path) => {
    return {
      [path]: parseContent(path, validatedAndFormatedContent[path])
    };
  });
};

export async function restoreParser(storage) {
    if (storage.parser) {
        logger.debug(() => 'when restore parser for request, use existing parser in storage, not really restore');
        return storage.parser;
    }
    const permission = storage.permission;
    logger.debug(() => `restore parser for permission ${permission} from cache`);
    const parserFromCache = await cache.get(CLUSTER_MANIFEST_PARSER + `${permission}`);
    const parser = Parser.fromExistData(storage.manifest, JSON.parse(parserFromCache));
    parser.cache = cache;
    return parser;
}

export async function updateManifestInfo(parser, storage) {
    const newHash = objectHash(parser.manifest);
    const isCluster = process.env.VUE_APP_DOCHUB_CLUSTER === 'on';
    if (isCluster) {
        storage.hash = newHash;
        storage.manifestHash = newHash;
        storage.parser = null;
        await cache.set(CLUSTER_MANIFEST_PARSER + `${storage.permission}`, JSON.stringify(parser));
        await cache.set(CLUSTER_MANIFEST + `${storage.permission}`, JSON.stringify(storage));
        await cache.set(CLUSTER_COMMAND_REFRESH_TIMESTAMP, Date.now());
    } else {
        storage.hash = newHash;
        storage.manifestHash = newHash;
        storage.hash = storage.manifestHash;
    }
}
