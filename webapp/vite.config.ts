import { rm } from 'node:fs/promises';
import path from 'node:path';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const MOCK_WORKER_FILE = 'mockServiceWorker.js';

function dropMockWorker(useMocks: boolean): Plugin {
  let outDir = 'dist';
  return {
    name: 'drop-mock-service-worker',
    apply: 'build',
    configResolved(config) {
      outDir = path.resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      if (useMocks) return;
      await rm(path.join(outDir, MOCK_WORKER_FILE), { force: true });
    },
  };
}

const BACKEND = 'http://localhost:8000';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  return {
    base: './',
    plugins: [react(), dropMockWorker(env.VITE_USE_MOCKS === 'true')],
    server: {
      proxy: {
        '/app-api': { target: BACKEND, changeOrigin: true },
        '/operator-api': { target: BACKEND, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: 'hidden',
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('@maxhub/max-ui')) return 'max-ui';
            if (id.includes('@tanstack')) return 'react-query';
            if (/[\\/]node_modules[\\/](\.pnpm[\\/])?(react|react-dom|scheduler|react-router|react-router-dom)[@\\/]/.test(id)) {
              return 'react';
            }
            return undefined;
          },
        },
      },
    },
  };
});
