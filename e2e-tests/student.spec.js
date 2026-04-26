const { test, expect } = require('@playwright/test');
const { setupTelegramAndCdnRoutes, sleep } = require('./fixtures');

const API_ME = {
  full_name: "Ali Valiyev",
  group_name: 'nF-2506',
  mars_id: '1001',
  phone_number: '+998901112233',
  avatar_emoji: '🎓',
  registered: null,
  last_active: null,
  channel_link: 'https://t.me/testchannel',
};

async function setupStudentApiMocks(page) {
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const method = route.request().method();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });

    if (u.includes('/api/me')) return json(API_ME);
    if (u.includes('/api/class-schedule')) {
      return json({
        has_class: false,
        class_time: null,
        group_name: API_ME.group_name,
        day_type: 'ODD',
        today: '2026-04-26',
        att_status: null,
      });
    }
    if (method === 'POST' && u.includes('/api/student/checkin')) {
      return json({ already_done: true, xp_gained: 0, streak_bonus: 0, leveled_up: false });
    }
    if (u.includes('/api/student/progress')) {
      return json({
        xp: 150,
        level: 2,
        level_name: "O'quvchi",
        next_level_xp: 250,
        streak_days: 3,
        attend_count: 5,
        hw_conf_count: 2,
        rank: 1,
        mood_today: null,
      });
    }
    if (u.includes('/api/attendance') && method === 'GET') return json({ date: '2026-04-26', status: null });
    if (u.includes('/api/student/xp-reset-notice')) return json({ show: false });
    if (u.includes('/api/homework')) return json({ exists: false });
    if (u.includes('/api/hw-history')) return json({ items: [] });
    if (u.includes('/api/student/leaderboard/group')) return json({ leaders: [] });
    if (u.includes('/api/student/leaderboard') && !u.includes('global') && !u.includes('monthly')) {
      return json({ group_name: API_ME.group_name, leaders: [] });
    }
    if (u.includes('/api/student/leaderboard/global')) return json({ leaders: [] });
    if (u.includes('/api/student/leaderboard/monthly')) return json({ leaders: [] });
    if (u.includes('/api/student/daily-challenge')) return json({});
    if (u.includes('/api/game/')) return json({ ok: true, leaders: [], messages: [], rooms: [] });
    if (u.includes('/api/chat')) return json({ messages: [] });
    if (u.includes('/api/public/groups')) return json({ groups: ['nF-2506'] });
    return json({});
  });

  await page.route('**/manifest.json', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ name: 'Mars IT Test' }) }),
  );
}

async function openStudentMiniApp(page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('onboarding_done', '1');
    } catch (_) {
      /* file:// yoki maxsus muhit */
    }
  });
  await setupTelegramAndCdnRoutes(page);
  await setupStudentApiMocks(page);
  await page.goto('/webapp/student.html', { waitUntil: 'domcontentloaded' });
  await sleep(2500);
}

test.describe('student.html', () => {
  test('sarlavha va ism API dan to‘g‘ri ko‘rinadi', async ({ page }) => {
    await openStudentMiniApp(page);
    await expect(page.locator('#hdrName')).toHaveText(API_ME.full_name);
    await expect(page.locator('#hdrGroup')).toHaveText(API_ME.group_name);
  });

  test('pastki tab: Uy vazifasi sahifasi', async ({ page }) => {
    await openStudentMiniApp(page);
    await page.locator('#tab-homework').click();
    await expect(page.locator('#page-homework.active')).toBeVisible();
  });

  test('Progress tab va daraja kartochkasi', async ({ page }) => {
    await openStudentMiniApp(page);
    await page.locator('#tab-progress').click();
    await expect(page.locator('#page-progress.active')).toBeVisible();
    await sleep(800);
    await expect(page.locator('#progressContent .level-card')).toBeVisible();
  });

  test('JS pageerror yo‘q (stub muhitida)', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await openStudentMiniApp(page);
    const filtered = errors.filter(
      (e) =>
        !e.includes('fetch') &&
        !e.includes('Failed to') &&
        !e.includes('NetworkError') &&
        !e.includes('net::') &&
        !e.includes('Load failed') &&
        !e.includes('AbortError') &&
        !e.includes('ResizeObserver'),
    );
    expect(filtered, `JS xatolar: ${JSON.stringify(filtered)}`).toEqual([]);
  });

  test('Guruh reytingi tab', async ({ page }) => {
    await openStudentMiniApp(page);
    await page.locator('#tab-group-lb').click();
    await expect(page.locator('#page-group-lb.active')).toBeVisible();
    await sleep(600);
    await expect(page.locator('#groupLbContent')).toBeVisible();
  });
});
