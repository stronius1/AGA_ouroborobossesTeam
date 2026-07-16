'use strict';


const hex = require('text-hex');

let Color; // будем подгружать динамически

// Синхронная обертка
function getColor(input) {
  if (!Color) throw new Error('Color module not loaded');
  return Color(input);
}

// Асинхронная инициализация
async function initColor() {
  if (Color) return;
  const mod = await import('color'); // динамический ESM импорт
  Color = mod.default;
}

/**
 * Generate a color for a given name. But be reasonably smart about it by
 * understanding name spaces and coloring each namespace a bit lighter so they
 * still have the same base color as the root.
 *
 * @param {string} namespace The namespace
 * @param {string} [delimiter] The delimiter
 * @returns {string} color
 */
module.exports = function colorspace(namespace, delimiter) {
  var split = namespace.split(delimiter || ':');
  var base = hex(split[0]);

  if (!split.length) return base;

  for (var i = 0, l = split.length - 1; i < l; i++) {
    base = getColor(base)
    .mix(getColor(hex(split[i + 1])))
    .saturate(1)
    .hex();
  }

  return base;
};

module.exports.initColor = initColor;
