import type { UserConfig } from 'vite';
import type { readProjectSettings } from './project-config.mjs';
export function createViteSettings(settings: ReturnType<typeof readProjectSettings>): UserConfig;
