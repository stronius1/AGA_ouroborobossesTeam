import env from '@front/helpers/env';
import requests from '@front/helpers/requests';
import {buildUserMenu} from '@global/manifest/services/menu-builder.mjs';
import queryDriver from '@front/manifest/query.js';

export async function getUserMenu(manifest) {
    if (env.isBackendMode) {
        const url = 'backend://user-menu';
        return (await requests.request(url)).data;
    } else {
        return await buildUserMenu(manifest, queryDriver);
    }
}
