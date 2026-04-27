const { test, expect } = require('@playwright/test');
const { setupTelegramAndCdnRoutes, sleep } = require('./fixtures');

async function mockAdminMiniApi(page, { loggedIn = false } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    const headers = route.request().headers();
    const auth = headers.authorization || '';
    const isBearer = auth.startsWith('Bearer ');
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });

    if (url.includes('/api/mini-admin/login') && method === 'POST') {
      return json({ ok: true, token: 'test-token', username: 'admin' });
    }
    if (url.includes('/api/mini-admin/logout') && method === 'POST') {
      return json({ ok: true });
    }

    if (url.includes('/api/admin/me')) {
      if (loggedIn || isBearer) return json({ ok: true, user_id: -1 });
      return json({ ok: false, error: 'Unauthorized', code: 'unauthorized' }, 401);
    }

    if (!isBearer && !loggedIn) {
      return json({ ok: false, error: 'Unauthorized', code: 'unauthorized' }, 401);
    }

    if (url.includes('/api/admin/profile')) {
      return json({ ok: true, display_name: 'Admin Test', avatar_emoji: '👨‍💼', referral_pending: 2 });
    }
    if (url.includes('/api/admin/stats')) {
      return json({
        ok: true,
        total_students: 15,
        today_present: 11,
        today_absent: 2,
        today_pending: 2,
      });
    }
    if (url.includes('/api/admin/warnings')) {
      return json({ ok: true, absent_3days: [], no_homework: [] });
    }
    if (url.includes('/api/admin/weekly-stats')) {
      return json({ days: [] });
    }

    return json({ ok: true });
  });
}

test.describe('admin-mini functional', () => {
  test('token bo‘lmasa login sahifa chiqadi', async ({ page }) => {
    await setupTelegramAndCdnRoutes(page);
    await mockAdminMiniApi(page, { loggedIn: false });
    await page.goto('/webapp/admin-mini.html', { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#loginPage')).toBeVisible();
    await expect(page.locator('#headerTitle')).toBeHidden();
  });

  test('token bilan dashboard statistikasi ko‘rinadi', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('miniAdminToken', 'test-token');
      localStorage.setItem('miniAdminUser', 'admin');
    });
    await setupTelegramAndCdnRoutes(page);
    await mockAdminMiniApi(page, { loggedIn: true });
    await page.goto('/webapp/admin-mini.html', { waitUntil: 'domcontentloaded' });
    await sleep(700);

    await expect(page.locator('#loginPage')).toBeHidden();
    await expect(page.locator('#headerTitle')).toHaveText('Admin Test');
    await expect(page.locator('#mainContent')).toContainText('15');
    await expect(page.locator('#mainContent')).toContainText('11');
  });

  test('login form orqali kirish ishlaydi', async ({ page }) => {
    await setupTelegramAndCdnRoutes(page);
    await mockAdminMiniApi(page, { loggedIn: false });
    await page.goto('/webapp/admin-mini.html', { waitUntil: 'domcontentloaded' });

    await page.fill('#loginUsername', 'admin');
    await page.fill('#loginPassword', 'secret');
    await page.click('#loginBtn');
    await sleep(600);

    await expect(page.locator('#loginPage')).toBeHidden();
    await expect(page.locator('#headerTitle')).toHaveText('Admin Test');
  });
});
