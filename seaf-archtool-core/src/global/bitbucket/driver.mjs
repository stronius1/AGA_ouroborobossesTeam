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
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Alexander Romashin <romashin.a.va@sberbank.ru>, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2024
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
*/

function _addAuthToHeader(params, config) {
    if (!params.headers) params.headers = {};
    // eslint-disable-next-line no-undef
    params.headers['Authorization'] = `Bearer ${config.personalToken || Vuex?.state?.access_token}`;
    params.headers['X-Atlassian-Token'] = 'no-check';
}

export default function(config) {
    this.axiosInterceptor = async(params) => {
        const urlNeedAuth = config.bitbucket_server && ((new URL(params.url)).host === (new URL(config.bitbucket_server)).host);
        if (urlNeedAuth && ['v1', 'v2'].includes(config.bitbucketWriteMode)) {
            _addAuthToHeader(params, config);
        } else if (urlNeedAuth && ['v1', 'v2'].includes(config.bitbucketMode)) {
            _addAuthToHeader(params, config);
        }
        return params;
    };

    this.makeFileURI = (projectID, repositoryId, source, branch) => {
        switch (config.bitbucketMode) {
            case 'v1':
                return new URL(
                    `rest/api/1.0/projects/${projectID}/repos/${repositoryId}/raw/`
                    + encodeURIComponent(source).split('%2F').join('/')
                    + `?at=${branch}`
                    , config.bitbucket_server);
            case 'v2':
                return new URL(
                    `/2.0/repositories/${projectID}/${repositoryId}/src/${branch}/`
                    + encodeURIComponent(source).split('%2F').join('/')
                    , config.bitbucket_server);
            case 'adapter':
                return new URL('/bitbucket/file/' +
                    encodeURIComponent(source).split('%2F').join('/') +
                    `?project=${encodeURIComponent(projectID)}` +
                    `&repo=${encodeURIComponent(repositoryId)}` +
                    `&branch=${encodeURIComponent(branch)}`,
                    config.bitbucketAdapterUrl);
            default:
                throw Error('Некорректно указано значение VUE_APP_DOCHUB_BITBUCKET_MODE');
        }
    };

    this.makeSourceURI = (projectID, repositoryId) => {
        const result_v2 = new URL(
            `/2.0/repositories/${projectID}/${repositoryId}/src`,
            config.bitbucket_server
        );
        return result_v2;
    };
    
    this.branchInfo = (projectID, repositoryId, branch) => {
        if(config.bitbucketMode === 'adapter') {
            return new URL('/commit/hash' +
                `?project=${encodeURIComponent(projectID)}` +
                `&repo=${encodeURIComponent(repositoryId)}` +
                `&branch=${encodeURIComponent(branch)}`,
                config.bitbucketAdapterUrl);
        } else {
            return new URL(
                `rest/api/1.0/projects/${projectID}/repos/${repositoryId}/branches?filterText=${encodeURIComponent(branch)}`,
                config.bitbucket_server
            );
        }
    };
}
