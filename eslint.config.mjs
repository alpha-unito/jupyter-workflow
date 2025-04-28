// @ts-check

import eslint from '@eslint/js';
import prettierConfig from 'eslint-config-prettier';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/*.d.ts',
      '**/lib',
      '**/__tests__',
      '.git',
      '.github',
      '.idea',
      '.pytest_cache',
      '.yarn',
      '.venv',
      'build',
      'coverage',
      'dist',
      'docs',
      'examples',
      'jupyter_workflow',
      'node_modules',
      'tests',
      'venv'
    ]
  },
  eslint.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      '@typescript-eslint/naming-convention': [
        'error',
        {
          'selector': 'interface',
          'format': [
            'PascalCase'
          ],
          'custom': {
            'regex': '^I[A-Z]',
            'match': true
          }
        }
      ],
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          'args': 'none'
        }
      ],
      '@typescript-eslint/no-esplicit-any': 'off',
      '@typescript-eslint/no-namespace': 'off',
      '@typescript-eslint/no-use-before-define': 'off',
      '@typescript-eslint/quotes': [
        'error',
        'single',
        {
          'avoidEscape': true,
          'allowTemplateLiterals': false
        }
      ],
      'curly': [
        'error',
        'all'
      ],
      'eqeqeq': 'error',
      'prefer-arrow-callback': 'error'
    }
  },
  prettierConfig
);