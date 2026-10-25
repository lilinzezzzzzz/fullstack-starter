import type { PlaywrightTestConfig } from '@playwright/test';
import type { readProjectSettings } from './project-config.mjs';
export function createPlaywrightSettings(
  settings: ReturnType<typeof readProjectSettings>['testing'],
): PlaywrightTestConfig;
