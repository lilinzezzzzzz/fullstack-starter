import { defineConfig } from 'vite';
import { configFile, readProjectSettings } from './scripts/project-config.mjs';
import { createViteSettings } from './scripts/vite-settings.mjs';

export default defineConfig(createViteSettings(readProjectSettings(configFile)));
