import fs from 'fs';
import path from 'path';
import semver from 'semver';
import { execSync } from 'child_process';

if (!process.env.NPM_TOKEN) {
  console.error('❌ Ошибка: Переменная окружения NPM_TOKEN не задана!');
  process.exit(1);
}

const registryFlag = process.argv.find(arg => arg.startsWith('--registry='))
    , versionFlag  = process.argv.find(arg => arg.startsWith('--version='))
    ;

let registry = "https://gitverse.ru/api/packages/seafteam/npm/";
if (registryFlag) {
  // Если флаг передан, вырезаем значение после знака "="
  const registryShortName = registryFlag.split('=')[1];
  switch (registryShortName.toLowerCase()) {
    case 'npmjs.org':
      registry = "https://registry.npmjs.org/"
      console.log('✅ Используем публичный NPM реестр');
      break;

    case 'gitverse.ru':
      console.log('✅ Используем GitVerse NPM реестр');
      break;

    default:
      console.log('⚠️  Неизвестный реестр, используем GitVerse NPM реестр');
  }

} else {
  console.log('✅ Используем GitVerse NPM реестр');
}

let version;
if (versionFlag) {
  version = versionFlag.split('=')[1];
} else {
  // Получаем актуальную версию из основного package.json и патчим в package.plugins.json
  const pkgJSON = JSON.parse(fs.readFileSync('./package.json', 'utf-8'));
  version = pkgJSON.version;
}

console.log(`🚀 Подготовка к публикации артефактов плагина. Версия: ${version}`);

const dist = path.resolve('./dist');
if (!fs.existsSync(dist)) {
  console.error(`❌ Ошибка: Папка ${dist} не найдена. Сначала нужно запустить сборку (npm run plugin)!`);
  process.exit(1);
}

try {
  const pkgPluginJSON = JSON.parse(fs.readFileSync('./patterns/plugin.publish/package.json', 'utf-8'));
  
  pkgPluginJSON.publishConfig.registry = registry;
  pkgPluginJSON.version = version;
  
  // Записываем обновленный package.json внутрь папки dist
  fs.writeFileSync(
    path.join(dist, 'package.json'), 
    JSON.stringify(pkgPluginJSON, null, 2)
  );
  fs.copyFileSync('./patterns/plugin.publish/.npmrc', 'dist/.npmrc');
  fs.copyFileSync('./LICENSE'                       , 'dist/LICENSE');
  fs.copyFileSync('./NOTICE'                        , 'dist/NOTICE');

  console.log(`✅ Версия ${version} успешно прописана в package.json для публикации`);
  console.log(`📦 Публикация пакета из папки dist в реестр ${registry}`);

  const prereleaseComponents = semver.prerelease(version);
  
  // Если это пререлиз (массив не null), берем самый первый элемент (например, 'rc' или 'dev')
  // Если это стабильная версия, ставим 'latest'
  const tag = prereleaseComponents && prereleaseComponents.length > 0
    ? prereleaseComponents[0]
    : 'latest';

  execSync(`cd ${dist} && npm publish . --access public --tag=${tag}`, { 
    stdio: 'inherit',
    env: {
      ...process.env,
    }
  });
  
  console.log('🎉 Пакет артефактов успешно опубликован!');
} catch (error) {
  console.error('❌ Ошибка в процессе публикации:', error.message);
} finally {
  const tmpPkgJSON = path.join(dist, 'package.json')
      , tmpNPMRc   = path.join(dist, '.npmrc')
      ;

  if (fs.existsSync(tmpPkgJSON)) fs.unlinkSync(tmpPkgJSON);
  if (fs.existsSync(tmpNPMRc))   fs.unlinkSync(tmpNPMRc);

  console.log('🧹 Временные файлы удалены.');
}