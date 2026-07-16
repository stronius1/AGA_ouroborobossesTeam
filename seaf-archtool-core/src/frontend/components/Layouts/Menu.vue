<!--
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru

  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      R.Piontik <r.piontik@mail.ru>

  Contributors:
      R.Piontik <r.piontik@mail.ru> - 2023
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <v-list density="compact">
    <errexp v-if="error" v-bind:error="error" />
    <v-list-item v-else>
      <v-text-field
        density="compact"
        clearable
        v-bind:model-value="filter.text"
        v-on:update:model-value="inputFilter">
        <template #append>
          <v-icon>
            mdi-magnify
          </v-icon>
        </template>
      </v-text-field>
    </v-list-item>

    <v-list-item
      v-if="archChooserEnabled"
      class="menu-item"
      v-bind:href="`/archChooser`"
      v-on:click.prevent="onClickMenuItem($event, {route: '/archChooser'})">
      <v-list-item-title class="menu-item-header">
        Архитектура: {{ archName }}
      </v-list-item-title>
    </v-list-item>

    <template v-for="(item, i) in menu">
      <v-list-item
        v-if="(item.route !== '/problems') || (problems.length)"
        v-bind:key="i"
        v-bind:href="item.route"
        v-bind:class="{ 'menu-item': true, 'menu-item-selected': isMenuItemSelected(item) }"
        v-bind:style="{ 'padding-left': '' + (item.level * 8) + 'px' }"
        v-on:dragstart.prevent
        v-on:click.prevent="onClickMenuItem($event, item)">
        <template #prepend>
          <v-icon
            v-if="item.isGroup"
            class="menu-item-action"
            v-on:click.prevent.stop="onClickMenuExpand(item)">
            <template v-if="isExpandItem(item)">mdi-chevron-down</template>
            <template v-else>mdi-chevron-right</template>
          </v-icon>
          <v-icon v-else class="menu-item-action menu-item-leaf-icon">mdi-circle-small</v-icon>
        </template>

        <v-list-item-title
          v-bind:class="[{ 'text-error': item.route === '/problems' },'menu-item-header']">
          {{ getMenuItemTitle(item) }}
        </v-list-item-title>

        <template v-if="item.icon" #append>
          <v-icon class="menu-item-action menu-item-ico">
            {{ item.icon }}
          </v-icon>
        </template>
      </v-list-item>
    </template>
  </v-list>
</template>

<script>
  import uri from '@front/helpers/uri';
  import errexp from '@front/components/JSONata/JSONataErrorExplainer.vue';
  import { getUserMenu } from '@front/helpers/menu.mjs';
  import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
  import userRightStore from '@front/store/userRightStore.js';
  import consts from '@front/consts.js';
  import env from '@front/helpers/env';

  const logger = getLoggerWithTag('Menu.vue');

  export default {
    name: 'Menu',
    components: {
      errexp
    },
    data() {
      return {
        // Открытые пункты меню
        currentRoute: this.$router.currentRoute,
        archChooserEnabled: env.archChooserEnabled,
        error: null,
        treeMenu: null,
        treeMenuRequestId: 0,
        filter: {
          text: '',
          query: '',
          timer: null
        },
        menuCache: null,
        expands: {
          architect: true,
          docs: true
        }
      };
    },
    computed: {
      // Выясняем сколько значимых отклонений зафиксировано
      // исключения не учитываем
      problemsCount() {
        let result = 0;
        this.problems.map((validator) => {
          (validator.items || []).map((problem) =>
            !problem.exception && result++
          );
        });
        return result;
      },
      problems() {
        return this.$store.state.problems || [];
      },
      currentSeafRoute() {
        const url = new URL(this.currentRoute.fullPath, window.location.origin);
        url.searchParams.delete(consts.roleModelV2.urlAliasParamName);
        url.searchParams.delete(consts.roleModelV2.urlOriginAliasParamName);
        return {
          fullPath: decodeURI(url.pathname + url.search),
          path: decodeURI(url.pathname)
        };
      },
      menu() {
        const result = [];
        const expand = (node, location) => {
          for (const key in node.items) {
            const item = node.items[key];
            const itemLocation = (location || []).concat([key]);
            const menuItem = {
              title: item.title,
              route: item.route,
              icon: item.icon,
              level: itemLocation.length - 1,
              location: itemLocation.join('/')
            };

            result.push(menuItem);

            if (Object.keys(item.items).length) {
              menuItem.isGroup = true;
              if (this.expands[menuItem.location] || this.filter.query) {
                expand(item, itemLocation);
              }
            }
          }
        };

        this.treeMenu && expand(this.treeMenu);

        return result;
      },
      archName() {
        const current = userRightStore.getCurrent();
        return current?.title || current?.alias || 'Не выбрана или выбрана несуществующая (недоступная). Нажмите, сюда, чтобы перейти к выбору';
      }
    },
    watch: {
      manifest() {
        this.menuCache = null;
        this.refreshTreeMenu();
      },
      $route(to) {
        this.currentRoute = to;
        this.refreshTreeMenu();
      },
      'filter.query'() {
        this.refreshTreeMenu();
      },
      'filter.text'(value) {
        if (this.filter.timer) clearTimeout(this.filter.timer);

        const len = (this.menuCache || []).length;
        let sens = 50;

        if (len > 1000) sens = 500;
        else if (len > 500) sens = 300;

        this.filter.timer = setTimeout(() => {
          this.filter.query = value && value.length > 1 ? value.toLocaleLowerCase() : '';
        }, sens);
      }
    },
    mounted() {
      this.refreshTreeMenu();
    },
    methods: {
      async buildTreeMenu() {
        const result = { items: {} };
        try {
          const dataset = (this.menuCache ? this.menuCache : await getUserMenu(this.manifest)) || [];
          const currentSeafRoute = this.currentSeafRoute;

          logger.debug(() => [
            'build menu tree',
            {title: 'menu dataset', obj: dataset},
            {title: 'filter', obj: this.filter}
          ]);
          !this.menuCache && this.$nextTick(() => this.menuCache = dataset);

          dataset.map((item) => {
            logger.trace(() => [{title: 'process menu item', obj: item}]);
            if (!this.isInFilter(item.location)) {
              logger.trace(() => [{title: 'menu item reject by filter', obj: item}]);
              return;
            }
            const location = item.location?.split('/');
            if (!location) {
              logger.trace(() => [{ title: 'item location in element not exist after split by /', obj: item}]);
              return;
            }
            let node = result;
            let key = null;
            for (let i = 0; i < location.length; i++) {
              key = location[i];
              !node.items[key] && (node.items[key] = { title: key, items: {} });
              node = node.items[key];
            }
            node.title = item.title;
            node.route = item.route;
            node.icon = item.icon;
            if ((node.route === currentSeafRoute.fullPath) || (node.route === currentSeafRoute.path)) {
              this.$nextTick(() => {
                let subLocation = null;
                location.map((item) => {
                  subLocation = subLocation ? `${subLocation}/${item}` : item;
                  if (!this.expands[subLocation])
                    this.expands[subLocation] = true;
                });
              });
            }
          });
          this.error = null;
        } catch (err) {
          logger.error(() => 'Error when build menu tree', err);
          this.error = err;
        }
        return result;
      },
      async refreshTreeMenu() {
        const requestId = ++this.treeMenuRequestId;
        const treeMenu = await this.buildTreeMenu();

        if (requestId === this.treeMenuRequestId) {
          this.treeMenu = treeMenu;
        }
      },
      isExpandItem(item) {
        return this.expands[item.location];
      },
      // Прокладка сделана т.к. инпут с v-model тупит при большом меню
      inputFilter(text) {
        this.filter.text = text;
      },
      isInFilter(text) {
        if (!this.filter.query) return true;
        const struct = this.filter.query.split(' ');
        const request = text.toLocaleLowerCase();
        for (let i = 0; i < struct.length; i++) {
          if (struct[i] && (request.indexOf(struct[i]) < 0)) return false;
        }
        return true;
      },
      getMenuItemTitle(item) {
        return item.route !== '/problems' ? item.title : item.title + ' (' + this.problemsCount + ')';
      },
      isMenuItemSelected(item) {
        return (item.route === this.currentSeafRoute.fullPath) ||
          (item.route === this.currentSeafRoute.path);
      },
      onClickMenuItem($event, item) {
        if (item.route) {
          if (uri.isExternalURI(item.route)) {
            window.open(item.route, '_blank');
          } else {
            if ($event.ctrlKey) {
              const routeData = this.$router.resolve(item.route);
              window.open(routeData.href, '_blank');
            } else {
              this.$router.push(item.route).catch(() => null);
            }
          }
        } else this.onClickMenuExpand(item);
      },
      onClickMenuExpand(item) {
        if (!item.isGroup) return;
        this.expands[item.location] = !this.expands[item.location];
      },
      //отрабатывает при клике на элементе меню
      getLevel(item) {
        return item.route.split('/').length;
      }
    }
  };
</script>

<style scoped>
  .menu-item {
    min-height: 20px !important;
    margin-top: 2px;
    margin-bottom: 2px;
  }

  .menu-item-action {
    padding: 0;
    margin: 2px !important;
  }

  .menu-item-leaf-icon {
    color: rgba(0, 0, 0, 0.38);
    pointer-events: none;
  }


  .menu-item-header {
    display: block;
    line-height: 20px;
    min-height: 20px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 400;
    white-space: normal;
    overflow: visible;
    text-overflow: unset;
  }

  .menu-item-ico {
    margin-left: 8px !important;
  }

  .menu-item-selected {
    background: #00755D;
  }

  .menu-item-selected * {
    color: #fff !important;
  }

  /* Hover только если нет класса menu-item-selected */
  .menu-item:not(.menu-item-selected):hover {
    background-color: #00987933; /* Светлый оттенок зелёного (на основе #00755D) */
  }
</style>
