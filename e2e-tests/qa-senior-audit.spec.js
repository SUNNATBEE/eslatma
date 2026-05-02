/**
 * Senior Q/A: barcha Mini App HTML lar (HTTP + stub API + konsol/pageerror).
 * @see audit-helpers.js
 */
const { test, expect } = require('@playwright/test');
const {
  createAuditBag,
  attachAuditCollectors,
  assertAuditClean,
  setupTelegramAndCdnRoutes,
  setupGamesAuditMocks,
  setupCuratorLoggedOutMocks,
  setupCuratorLoggedInMocks,
  setupAdminHtmlAuditMocks,
  setupGuideSmokeMocks,
  sleep,
} = require('./audit-helpers');

async function openWithMocks(page, path, setupMocks) {
  await setupTelegramAndCdnRoutes(page);
  await setupMocks(page);
  await page.goto(path, { waitUntil: 'domcontentloaded' });
  await sleep(2200);
}

test.describe('QA Senior: games.html', () => {
  test('init + home + leaderboard: xatosiz', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await openWithMocks(page, '/webapp/games.html', setupGamesAuditMocks);
    await expect(page.locator('#page-home.active')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('#hdrXp')).toContainText('XP');
    assertAuditClean(bag, 'games');
  });
});

test.describe('QA Senior: guide.html', () => {
  test('yuklanish (statik + API stub)', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await openWithMocks(page, '/webapp/guide.html', setupGuideSmokeMocks);
    await expect(page.locator('body')).toBeVisible();
    assertAuditClean(bag, 'guide');
  });
});

test.describe('QA Senior: curator.html', () => {
  test('login sahifa (sessiya yoq)', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await openWithMocks(page, '/webapp/curator.html', setupCuratorLoggedOutMocks);
    await expect(page.locator('#page-login.active')).toBeVisible({ timeout: 12000 });
    assertAuditClean(bag, 'curator-login');
  });

  test('kirgan: barcha pastki tablar', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await setupTelegramAndCdnRoutes(page);
    await setupCuratorLoggedInMocks(page);
    await page.goto('/webapp/curator.html', { waitUntil: 'domcontentloaded' });
    await sleep(2500);
    await expect(page.locator('#page-main.active')).toBeVisible({ timeout: 15000 });
    /* Har sahifada alohida curtabN-*; faol sahifa .active bilan tekshiramiz */
    const tabToPage = {
      students: 'main',
      attendance: 'attendance',
      messages: 'messages',
      stats: 'stats',
      yoqlama: 'yoqlama',
    };
    for (const t of ['attendance', 'messages', 'stats', 'yoqlama', 'students']) {
      /* Har sahifada boshqacha id (curtab / curtab2 / …); global switchCurTab chaqiramiz */
      await page.evaluate((name) => {
        if (typeof switchCurTab === 'function') switchCurTab(name);
      }, t);
      await sleep(550);
      await expect(page.locator(`#page-${tabToPage[t]}.active`)).toBeVisible({ timeout: 15000 });
    }
    assertAuditClean(bag, 'curator-tabs');
  });
});

test.describe('QA Senior: admin.html', () => {
  test('barcha yuqori tablar (dashboard → automsg)', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await setupTelegramAndCdnRoutes(page);
    await setupAdminHtmlAuditMocks(page);
    await page.goto('/webapp/admin.html', { waitUntil: 'domcontentloaded' });
    await sleep(2600);
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('#page-dashboard.active')).toBeVisible();
    const tabs = ['students', 'attendance', 'groups', 'actions', 'curators', 'automsg', 'dashboard'];
    for (const t of tabs) {
      await page.locator(`#tab-${t}`).click();
      await expect(page.locator(`#tab-${t}.active`)).toBeVisible();
      await expect(page.locator(`#page-${t}.active`)).toBeVisible();
      /* Faqat aktiv sahifadagi .spinner (yashirin tablardagi qolgan spinnerlarni hisobga olmaymiz) */
      await page.waitForFunction(
        () => {
          const pageEl = document.querySelector('#content .page.active');
          if (!pageEl) return true;
          return !pageEl.querySelector('.spinner');
        },
        null,
        { timeout: 20000 },
      );
      await sleep(200);
    }
    assertAuditClean(bag, 'admin.html');
  });
});
