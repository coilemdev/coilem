import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const localOutrunner = process.env.VITE_COILEM_EXPERIMENTAL_OUTRUNNER === '1';
const disabledOutrunnerModule = '\0coilem-disabled-outrunner';

export default defineConfig({
  // The local reference workspace is excluded from ordinary release bundles.
  define: {
    'import.meta.env.VITE_COILEM_EXPERIMENTAL_OUTRUNNER': JSON.stringify(localOutrunner ? '1' : '0'),
  },
  root: fileURLToPath(new URL('./src/public', import.meta.url)),
  publicDir: fileURLToPath(new URL('./public', import.meta.url)),
  cacheDir: fileURLToPath(new URL('./node_modules/.vite-public-boundary', import.meta.url)),
  plugins: [react(), ...(!localOutrunner ? [{
    // Rollup can emit unused dynamic-entry chunks even after their calls are
    // eliminated. Do not ship the experimental fixture in a release bundle.
    name: 'exclude-local-outrunner',
    enforce: 'pre' as const,
    resolveId(source: string, importer: string | undefined) {
      if (importer?.replaceAll('\\', '/').endsWith('/src/public/App.tsx')
        && ['./outrunner/project', './outrunner/OutrunnerWorkspace'].includes(source)) return disabledOutrunnerModule;
      return null;
    },
    load(id: string) {
      if (id !== disabledOutrunnerModule) return null;
      return 'export const DEFAULT_OUTRUNNER_PROJECT=null; export const OutrunnerWorkspace=null; export function parseOutrunnerProject(){throw new Error("Local experiment excluded from this build")}';
    },
  }] : [])],
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
