/**
 * UI audit: student.html + admin-mini.html
 * @see audit-helpers.js
 *
 * npm run test:e2e:audit
 * npm run test:e2e:audit:headed
 * npm run test:e2e:audit:trace
 */
const { test, expect } = require('@playwright/test');
const {
  createAuditBag,
  attachAuditCollectors,
  assertAuditClean,
  openStudentForAudit,
  openAdminMiniLoggedIn,
  sleep,
} = require('./audit-helpers');

test.describe('Audit: student.html', () => {
  test('barcha pastki tablar: aktiv sahifa + JS konsol xatosiz', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await openStudentForAudit(page);

    await expect(page.locator('#hdrName')).toHaveText('Audit Student');
    await expect(page.locator('#page-home.active')).toBeVisible();

    const tabs = [
      ['#tab-homework', '#page-homework'],
      ['#tab-progress', '#page-progress'],
      ['#tab-group-lb', '#page-group-lb'],
      ['#tab-chat', '#page-chat'],
      ['#tab-history', '#page-history'],
      ['#tab-games', '#page-games'],
      ['#tab-referral', '#page-referral'],
      ['#tab-home', '#page-home'],
    ];
    for (const [tabSel, pageSel] of tabs) {
      await page.locator(tabSel).click();
      await sleep(500);
      await expect(page.locator(`${pageSel}.active`)).toBeVisible({ timeout: 12000 });
    }

    await sleep(400);
    assertAuditClean(bag, 'student-audit');
  });
});

test.describe('Audit: admin-mini.html', () => {
  test('barcha nav tablar + header ⚙️ sozlamalar: yuklanish + API 4xx/5xx yo‘q', async ({ page }) => {
    const bag = createAuditBag();
    attachAuditCollectors(page, bag);
    await openAdminMiniLoggedIn(page);

    await expect(page.locator('#loginPage')).toBeHidden();
    await expect(page.locator('#headerTitle')).toHaveText('Audit Admin');

    const navTabs = [
      'dashboard',
      'students',
      'groups',
      'attendance',
      'leaderboard',
      'curators',
      'referral',
      'homework',
      'settings',
    ];
    for (const id of navTabs) {
      await page.locator(`#nav_${id}`).click();
      await expect(page.locator(`#nav_${id}.active`)).toBeVisible();
      await page.waitForFunction(
        () => !document.querySelector('#mainContent .loading'),
        null,
        { timeout: 20000 },
      );
      await sleep(200);
    }

    await page.locator('.header-icon-btn').click();
    await sleep(700);
    await expect(page.locator('#nav_settings.active')).toBeVisible();
    await expect(page.locator('#autoMsgOverviewBox')).toBeVisible();

    assertAuditClean(bag, 'admin-mini-audit');
  });
});
