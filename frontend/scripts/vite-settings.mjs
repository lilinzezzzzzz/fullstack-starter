import react from '@vitejs/plugin-react';
import { browserDefinitions } from './project-config.mjs';

export function createViteSettings(settings) {
  return {
    envDir: false,
    envPrefix: [],
    plugins: [react()],
    define: browserDefinitions(settings),
    build: {
      outDir: settings.frontend_dir,
      emptyOutDir: settings.frontend_clean_output,
    },
    server: {
      host: settings.vite.host,
      port: settings.vite.port,
      strictPort: settings.vite.strict_port,
      allowedHosts: settings.allowed_hosts,
      proxy: {
        '/api': {
          target: settings.vite.proxy_target,
          changeOrigin: settings.vite.change_origin,
        },
      },
    },
  };
}
