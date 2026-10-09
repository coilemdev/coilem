import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  root: fileURLToPath(new URL('./src/public', import.meta.url)),
  publicDir: fileURLToPath(new URL('./public', import.meta.url)),
  cacheDir: fileURLToPath(new URL('./node_modules/.vite-public-boundary', import.meta.url)),
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: fileURLToPath(new URL('./dist-public-boundary', import.meta.url)),
    emptyOutDir: true,
  },
});
