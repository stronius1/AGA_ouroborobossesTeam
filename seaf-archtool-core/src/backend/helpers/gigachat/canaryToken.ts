/**
 * Преобразует 8-значный цифровой код в строку из N символов с использованием заданного пула символов.
 *
 * @param {string} originalCode - 8-символьная строка цифр
 * @param {string} symbolPool - строка с символами для кодирования (например, длинной 100)
 * @param {string} [N] - длина выходной строки (если не задан, вычисляется автоматически)
 *
 * @returns {string} Строка из N символов из заданного пула
 *
 * @throws {Error} Ошибка при формировании токена
 *
 * @example
 * generateCanaryToken("01234567", "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz", 4) => "EUor"
 */
export const generateCanaryToken = (
  originalCode: string,
  symbolPool: string,
  N?: number
) => {
  if (!originalCode || !/^\d{8}$/.test(originalCode)) {
    throw new Error('КЭ AI -агента не задан или содержит ошибку');
  }

  const number = parseInt(originalCode, 10);
  const base = symbolPool.trim().length;

  if (base === 0) {
    throw new Error('Не задан пул символов для формирования токенов'); //
  }

  // Если И не задан, вычисляем минимальную необходимую длинну
  if (N === undefined) {
    // Вычисляем минимальное N, при котором base^N >= 10^8
    N = 1;
    while (base ** N < 10 ** 8) {
      N += 1;
    }
  }

  // Проверяем, что число в допустимом диапазоне
  const maxValue = base ** N - 1;
  if (number > maxValue) {
    throw new Error(
      `Число ${number} превышает максимальное значение ${maxValue} для ${N} символов с пулом из ${base} символов`
    );
  }

  // Преобразуем в систему счисления с оснванием base
  const result = [];
  let n = number;
  for (let i = 0; i < N; i++) {
    const remainder = n % base;
    n = Math.floor(n / base);
    result.push(symbolPool[remainder]);
  }

  return result.reverse().join('');
};

export const validateCannaryTokenSymbolsPool = (tokenPool: any) => {
  const result = {
    success: true,
    error: null
  };

  if (!(typeof tokenPool === 'string' && tokenPool.trim().length > 0)) {
    result.success = false;
    result.error =
      'Переменная "VUE_APP_GIGACHAT_CANARY_TOKEN_POOL" должна содержать строку с символами.';
  }

  return result;
};

export const validateGigachatAgentCI = (ci: any) => {
  const result = {
    success: true,
    error: null
  };

  if (!(typeof ci === 'string' && /^\d{8}$/.test(ci.slice(-8)))) {
    result.success = false;
    result.error =
      'Переменная "VUE_APP_GIGACHAT_AGENT_CI" должна содержать строку с CI (КЭ) AI-агента (GigaChat) c цифровым идентификатором из 8 цифр (Пример - CI12345678).';
  }

  return result;
};
