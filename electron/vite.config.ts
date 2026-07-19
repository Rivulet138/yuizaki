import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'path';

const rendererPort = Number.parseInt(process.env.RENDERER_PORT || '', 10);
const rendererRoot = path.resolve(__dirname, 'src/renderer');
const rendererInputs = {
  // UI window entry (Vue app)
  main: path.resolve(rendererRoot, 'index.html'),
  // Pet window entry (standalone Live2D layer)
  pet: path.resolve(rendererRoot, 'pet-window.html'),
};

export default defineConfig({
  base: './',
  plugins: [vue()],
  root: rendererRoot,
  optimizeDeps: {
    entries: ['index.html', 'pet-window.html'],
    include: [
      '@element-plus/icons-vue',
      '@pixiv/three-vrm',
      'easy-live2d',
      'element-plus',
      'pinia',
      'pixi.js',
      'pixi.js/unsafe-eval',
      'socket.io-client',
      'three',
      'three/examples/jsm/loaders/GLTFLoader.js',
      'vue',
      'vue-router',
    ],
  },
  build: {
    outDir: '../../dist/renderer',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1300,
    rolldownOptions: {
      onLog(level, log, handler) {
        if (
          log.code === 'INVALID_ANNOTATION' &&
          typeof log.id === 'string' &&
          log.id.includes('@vueuse/core')
        ) {
          return;
        }
        handler(level, log);
      },
      input: rendererInputs,
      output: {
        codeSplitting: {
          includeDependenciesRecursively: false,
          groups: [
            { name: 'element-icons', test: /node_modules[\\/]@element-plus[\\/]icons-vue/, priority: 100, entriesAware: true },
            { name: 'element-plus', test: /node_modules[\\/]element-plus/, priority: 90, entriesAware: true },
            {
              name: 'three-vendor',
              test: (id) => id.includes('@pixiv/three-vrm') || /node_modules[\\/]three[\\/]/.test(id),
              priority: 80,
              entriesAware: true,
            },
            { name: 'live2d-vendor', test: /node_modules[\\/]easy-live2d/, priority: 80, entriesAware: true },
            { name: 'pixi-vendor', test: /node_modules[\\/]pixi\.js/, priority: 70, entriesAware: true },
            {
              name: 'transport-vendor',
              test: (id) => id.includes('axios') || id.includes('socket.io-client'),
              priority: 60,
              entriesAware: true,
            },
            {
              name: 'vue-vendor',
              test: (id) => /node_modules[\\/](?:@vue|vue|pinia)[\\/]/.test(id),
              priority: 50,
              entriesAware: true,
            },
            { name: 'vendor', test: /node_modules/, priority: 1, entriesAware: true },
          ],
        },
      },
    },
  },
  server: {
    port: Number.isInteger(rendererPort) && rendererPort > 0 ? rendererPort : 5173,
    strictPort: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src/renderer'),
    },
  },
});
