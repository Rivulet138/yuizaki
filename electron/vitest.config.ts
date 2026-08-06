import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src/renderer'),
    },
  },
  test: {
    environment: 'happy-dom',
    include: [
      'src/main/__tests__/*.test.ts',
      'src/preload/__tests__/*.test.ts',
      'src/renderer/__tests__/*.test.ts',
    ],
    testTimeout: 15000,
  },
})
