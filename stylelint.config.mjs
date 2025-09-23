// @ts-check

/** @type {import('stylelint').Config} */
export default {
  extends: [
    'stylelint-config-recommended',
    'stylelint-config-standard',
    'stylelint-prettier/recommended',
  ],
  rules: {
    'property-no-vendor-prefix': null,
    'selector-class-pattern': '^([a-z][A-z\\d]*)(-[A-z\\d]+)*$',
    'selector-no-vendor-prefix': null,
    'value-no-vendor-prefix': null
  }
};
