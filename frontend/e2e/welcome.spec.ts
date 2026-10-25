import { expect, test } from '@playwright/test';

test('single FastAPI service serves Hello, assets and client-side navigation', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Hello, world.');
  await expect(page.getByText('前后端已连通')).toBeVisible();
  await expect(page.getByText(`Hello, ${await page.title()}!`)).toBeVisible();
  await page.goto('/welcome');
  await page.reload();
  await expect(page.getByText('前后端已连通')).toBeVisible();
  const missingAPI = await request.get('/api/missing', { headers: { Accept: 'text/html' } });
  expect(missingAPI.status()).toBe(404);
  expect((await missingAPI.json()).code).toBe('NOT_FOUND');
  expect((await request.get('/assets/missing.js')).status()).toBe(404);
  expect(errors).toEqual([]);
});

test('connection error is explained and retry reconnects to the real API', async ({ page }) => {
  await page.route('**/api/v1/hello', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'UNAVAILABLE',
        message: '测试服务暂时不可用',
        details: [],
        request_id: 'test-request',
      }),
    }),
  );
  await page.goto('/');
  await expect(page.getByText('连接检查失败')).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('测试服务暂时不可用');
  await page.unroute('**/api/v1/hello');
  await page.getByRole('button', { name: '重试连接' }).click();
  await expect(page.getByText('前后端已连通')).toBeVisible();
  await expect(page.getByText(`Hello, ${await page.title()}!`)).toBeVisible();
});

test('welcome stays available while API connection is loading', async ({ page }) => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/v1/hello', async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto('/');
  try {
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText('正在检查连接…')).toBeVisible();
  } finally {
    release();
  }
  await expect(page.getByText('前后端已连通')).toBeVisible();
});

test('narrow screen has no horizontal overflow and supports keyboard retry', async ({
  page,
}, testInfo) => {
  await page.setViewportSize(testInfo.project.metadata.mobileViewport);
  await page.goto('/');
  await expect(page.getByText('前后端已连通')).toBeVisible();
  await page.keyboard.press('Tab');
  const retry = page.getByRole('button', { name: '重新检查' });
  await expect(retry).toBeFocused();
  const response = page.waitForResponse((value) => value.url().endsWith('/api/v1/hello'));
  await page.keyboard.press('Enter');
  expect((await response).status()).toBe(200);
  await expect(page.getByText('前后端已连通')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
