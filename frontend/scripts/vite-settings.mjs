import { readFileSync } from 'node:fs';
import react from '@vitejs/plugin-react';
import { parse } from 'smol-toml';

const viteDevConfig = new URL('../configs/vite.toml', import.meta.url);
const devKeys = new Set(['host', 'port', 'proxy_target', 'strict_port', 'change_origin']);

export function readViteDevSettings(file = viteDevConfig) {
  const config = parse(readFileSync(file, 'utf8'), { integersAsBigInt: true });
  const unknown = Object.keys(config).filter((key) => !devKeys.has(key));
  if (unknown.length > 0) {
    throw new Error(`Vite config ${file}: unknown fields ${unknown.join(', ')}`);
  }

  const {
    host,
    port,
    proxy_target: target,
    strict_port: strictPort,
    change_origin: changeOrigin,
  } = config;
  if (typeof host !== 'string' || host.trim() === '') {
    throw new Error(`Vite config ${file}: host must be a non-empty string`);
  }
  if (typeof port !== 'bigint' || port < 1n || port > 65535n) {
    throw new Error(`Vite config ${file}: port must be an integer from 1 to 65535`);
  }
  const proxyURL =
    typeof target === 'string' && /^https?:\/\//i.test(target) ? URL.parse(target) : null;
  if (
    !proxyURL ||
    !['http:', 'https:'].includes(proxyURL.protocol) ||
    proxyURL.username ||
    proxyURL.password
  ) {
    throw new Error(`Vite config ${file}: proxy_target must be an HTTP(S) URL without credentials`);
  }
  if (strictPort !== true) {
    throw new Error(`Vite config ${file}: strict_port must be true`);
  }
  if (typeof changeOrigin !== 'boolean') {
    throw new Error(`Vite config ${file}: change_origin must be a boolean`);
  }

  return { host, port: Number(port), strictPort, proxy: { '/api': { target, changeOrigin } } };
}

export function createViteSettings(settings, devServer) {
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
    server: devServer && { ...devServer, allowedHosts: settings.allowed_hosts },
  };
}
