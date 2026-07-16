export const accumulateTokenCounter = (currentTokens, spentTokens) => {
  if (
    !(
      currentTokens &&
      typeof currentTokens === 'object' &&
      !Array.isArray(currentTokens)
    )
  ) {
    return;
  }

  for (const tokenType in currentTokens) {
    const count = spentTokens[tokenType];
    if (typeof count === 'number') {
      currentTokens[tokenType] += spentTokens[tokenType];
    }
  }
};
