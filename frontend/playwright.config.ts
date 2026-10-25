import { fileURLToPath } from 'node:url';
import { configFile, readProjectSettings } from './scripts/project-config.mjs';
import { createPlaywrightSettings } from './scripts/playwright-settings.mjs';

const settings = createPlaywrightSettings(readProjectSettings(configFile).testing);
export default { ...settings, testDir: fileURLToPath(new URL('./e2e', import.meta.url)) };
