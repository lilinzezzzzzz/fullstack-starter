import { defineConfig } from 'vite';
import { configFile, readProjectSettings } from './scripts/project-config.mjs';
import { createViteSettings, readViteDevSettings } from './scripts/vite-settings.mjs';

export default defineConfig(({ command }) => {
  const devServer = command === 'serve' ? readViteDevSettings() : undefined;
  return createViteSettings(readProjectSettings(configFile), devServer);
});
