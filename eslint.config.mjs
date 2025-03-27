// @ts-check

import eslint from '@eslint/js';
import prettier from 'eslint-plugin-prettier/recommended';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    plugins: {
      ['@typescript-eslint']: tseslint.plugin
    }
  },
  {
    ignores: ['node_modules/**', 'venv/**']
  },
  eslint.configs.recommended,
  tseslint.configs.strict,
  prettier,
  {
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 2018
      }
    },
    rules: {
      '@typescript-eslint/naming-convention': [
        'error',
        {
          selector: 'interface',
          format: ['PascalCase'],
          custom: {
            regex: '^I[A-Z]',
            match: true
          }
        }
      ],
      '@typescript-eslint/no-unused-vars': ['warn', { args: 'none' }],
      '@typescript-eslint/no-use-before-define': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/no-namespace': 'off',
      '@typescript-eslint/interface-name-prefix': 'off',
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/ban-ts-comment': ['warn', { 'ts-ignore': true }],
      '@typescript-eslint/no-restricted-types': 'error',
      '@typescript-eslint/no-non-null-asserted-optional-chain': 'warn',
      '@typescript-eslint/no-var-requires': 'off',
      '@typescript-eslint/no-empty-interface': 'off',
      '@typescript-eslint/triple-slash-reference': 'warn',
      '@typescript-eslint/no-inferrable-types': 'off',
      'id-match': ['error', '^[a-zA-Z_]+[a-zA-Z0-9_]*$'],
      'no-inner-declarations': 'off',
      'no-prototype-builtins': 'off',
      'no-control-regex': 'warn',
      'no-undef': 'warn',
      'no-case-declarations': 'warn',
      'no-useless-escape': 'off',
      'prefer-const': 'off',
      'sort-imports': [
        'error',
        {
          ignoreCase: true,
          ignoreDeclarationSort: true,
          ignoreMemberSort: false,
          memberSyntaxSortOrder: ['none', 'all', 'multiple', 'single'],
          allowSeparatedGroups: false
        }
      ]
    }
  }
);
