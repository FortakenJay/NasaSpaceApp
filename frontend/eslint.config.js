import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

const NETWORK_MSG = 'Network access lives in src/api/ only. Use the hooks exported from src/api (index.ts).';

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Centralized API: no fetch/XHR outside src/api, and no reaching past its public index.
      'no-restricted-globals': ['error', { name: 'fetch', message: NETWORK_MSG }, { name: 'XMLHttpRequest', message: NETWORK_MSG }],
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['**/api/client', '**/api/endpoints', '**/api/queries'], message: 'Import from src/api (index.ts) instead.' },
          { group: ['axios'], message: NETWORK_MSG },
        ],
      }],
    },
  },
  {
    files: ['src/api/**'],
    rules: { 'no-restricted-globals': 'off', 'no-restricted-imports': 'off' },
  },
);
