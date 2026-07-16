import generateAliasesResolver from 'esm-module-alias';

const aliases = {
    '@assets': './src/assets',
    '@global': './src/global',
    '@back': './src/backend'
};
export const resolve = generateAliasesResolver(aliases);
