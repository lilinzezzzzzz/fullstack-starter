import { defineConfig } from '@playwright/test';

export function createPlaywrightSettings(testing) {
  return defineConfig({
    fullyParallel: testing.fully_parallel,
    workers: testing.workers,
    retries: testing.retries,
    reporter: testing.reporter,
    timeout: testing.test_timeout_seconds * 1000,
    expect: { timeout: testing.expect_timeout_seconds * 1000 },
    metadata: { mobileViewport: { width: testing.mobile_width, height: testing.mobile_height } },
    use: {
      browserName: testing.browser,
      viewport: { width: testing.viewport_width, height: testing.viewport_height },
      trace: testing.trace,
      screenshot: testing.screenshot,
      actionTimeout: testing.action_timeout_seconds * 1000,
      navigationTimeout: testing.navigation_timeout_seconds * 1000,
    },
  });
}
