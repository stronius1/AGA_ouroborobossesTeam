/*
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
      R.Piontik <r.piontik@mail.ru> - 2024
*/

export default {
    isAvailable() {
      return document.fullscreenEnabled || false;
    },
    request(element) {
        element = element || document.documentElement;
        if (element.requestFullscreen) {
            return element.requestFullscreen();
          } else if (element.mozRequestFullScreen) {
            return element.mozRequestFullScreen();
          } else if (element.webkitRequestFullScreen) {
            return element.webkitRequestFullScreen();
          } else if (element.msRequestFullscreen) {
            return element.msRequestFullscreen();
          }
        return new Promise((success, reject ) => reject());
    },
    cancel() {
        if (document.exitFullscreen) {
            return document.exitFullscreen();
        } else if (document.webkitExitFullscreen) {
            return document.webkitExitFullscreen();
        } else if (document.mozCancelFullScreen) {
            return document.mozCancelFullScreen();
        } else if (document.msExitFullscreen) {
            return document.msExitFullscreen();
        }
    },
    isFullScreen() {
        return (document.fullscreenElement && document.fullscreenElement !== null) ||
        (document.webkitFullscreenElement && document.webkitFullscreenElement !== null) ||
        (document.mozFullScreenElement && document.mozFullScreenElement !== null) ||
        (document.msFullscreenElement && document.msFullscreenElement !== null);
    },
    watcher: null,
    toggle(element, callback, value) {
        if (!value && this.isFullScreen()) {
            this.cancel();
            clearInterval(this.watcher);
            this.watcher = null;
            callback(false);
          } else {
            this.request(element);
            this.watcher = setInterval(() => {
              if (!this.isFullScreen()) {
                clearInterval(this.watcher);
                this.watcher = null;
                callback(false);
              }
            }, 50);
            callback(true);
          }
    }
};
