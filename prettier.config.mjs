// @ts-check

/** @type {import('prettier').Config} */
export default {
  singleQuote: true,
  trailingComma: 'none',
  arrowParens: 'avoid',
  endOfLine: 'auto',
  overrides: [
    {
      files: 'package.json',
      options: {
        tabWidth: 4,
      }
    }
  ]
};
