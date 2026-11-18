import type { ServerOptions, UserConfig } from 'vite';
import type { readProjectSettings } from './project-config.mjs';
export function readViteDevSettings(file?: string | URL): ServerOptions;
export function createViteSettings(
  settings: ReturnType<typeof readProjectSettings>,
  devServer?: ServerOptions,
): UserConfig;
