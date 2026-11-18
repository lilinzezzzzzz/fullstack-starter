import react from '@vitejs/plugin-react';

export function createViteSettings(settings) {
  return {
    envDir: false,
    envPrefix: [],
    plugins: [react()],
    define: {
      // 浏览器只需要应用标识。
      __APPLICATION_INFO__: JSON.stringify({
        title: settings.application.title,
        version: settings.application.version,
      }),
    },
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
