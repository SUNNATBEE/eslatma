/**
 * Playwright QA audit yordamchilari (Telegram stub + API mock + konsol/pageerror).
 * student / admin-mini / games / curator / admin.html uchun.
 */
const { setupTelegramAndCdnRoutes, sleep } = require('./fixtures');

const IGNORE_PAGEERROR_SUBSTR = [
  'fetch',
  'Failed to',
  'NetworkError',
  'net::',
  'Load failed',
  'AbortError',
  'ResizeObserver',
];

const IGNORE_CONSOLE_SUBSTR = [
  'favicon',
  'ResizeObserver',
  'net::ERR',
  'Failed to load resource',
  '404',
  'sourcemap',
];

function createAuditBag() {
  return { pageErrors: [], consoleErrors: [], apiBadStatus: [] };
}

function attachAuditCollectors(page, bag) {
  page.on('pageerror', (err) => bag.pageErrors.push(err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') bag.consoleErrors.push(msg.text());
  });
  page.on('response', (res) => {
    const u = res.url();
    if (!u.includes('/api/')) return;
    if (res.status() >= 400) bag.apiBadStatus.push({ url: u, status: res.status() });
  });
}

function filterPageErrors(messages) {
  return messages.filter((e) => !IGNORE_PAGEERROR_SUBSTR.some((s) => e.includes(s)));
}

function filterConsoleErrors(messages) {
  return messages.filter((e) => !IGNORE_CONSOLE_SUBSTR.some((s) => e.includes(s)));
}

function assertAuditClean(bag, label = 'QA') {
  const pe = filterPageErrors(bag.pageErrors);
  const ce = filterConsoleErrors(bag.consoleErrors);
  const err = [];
  if (pe.length) err.push(`${label} pageerror: ${JSON.stringify(pe)}`);
  if (ce.length) err.push(`${label} console.error: ${JSON.stringify(ce)}`);
  if (bag.apiBadStatus.length) err.push(`${label} HTTP>=400: ${JSON.stringify(bag.apiBadStatus)}`);
  if (err.length) throw new Error(err.join('\n'));
}

async function setupStudentAuditMocks(page) {
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const method = route.request().method();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });

    if (u.includes('/api/me')) {
      return json({
        full_name: 'Audit Student',
        group_name: 'nF-2506',
        mars_id: '9001',
        phone_number: '+998901112233',
        avatar_emoji: '🎓',
        registered: true,
        last_active: '2026-05-01',
        channel_link: 'https://t.me/testchannel',
      });
    }
    if (u.includes('/api/class-schedule')) {
      return json({
        has_class: false,
        class_time: null,
        group_name: 'nF-2506',
        day_type: 'ODD',
        today: '2026-05-01',
        att_status: null,
      });
    }
    if (method === 'POST' && u.includes('/api/student/checkin')) {
      return json({ already_done: false, xp_gained: 5, streak_bonus: 0, leveled_up: false });
    }
    if (u.includes('/api/student/progress')) {
      return json({
        xp: 200,
        level: 3,
        level_name: "O'quvchi",
        next_level_xp: 400,
        streak_days: 2,
        attend_count: 10,
        hw_conf_count: 1,
        rank: 2,
        mood_today: null,
      });
    }
    if (u.includes('/api/attendance') && method === 'GET') return json({ date: '2026-05-01', status: null });
    if (u.includes('/api/attendance') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/student/xp-reset-notice')) {
      if (method === 'POST') return json({ ok: true });
      return json({ show: false });
    }
    if (u.includes('/api/homework')) return json({ exists: false });
    if (u.includes('/api/hw-history')) return json({ items: [] });
    if (u.includes('/api/student/hw-confirm-status')) return json({ confirmed: false });
    if (method === 'POST' && u.includes('/api/student/hw-confirm')) return json({ ok: true });
    if (u.includes('/api/student/leaderboard/group')) return json({ group_name: 'nF-2506', leaders: [] });
    if (u.includes('/api/student/leaderboard/global')) return json({ leaders: [] });
    if (u.includes('/api/student/leaderboard/monthly')) return json({ leaders: [] });
    if (u.includes('/api/student/leaderboard') && !u.includes('group') && !u.includes('global') && !u.includes('monthly')) {
      return json({ group_name: 'nF-2506', leaders: [] });
    }
    if (u.includes('/api/student/daily-challenge')) return json({});
    if (u.includes('/api/student/mood') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/student/avatar') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/student/logout') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/student/referral/invited')) return json({ items: [] });
    if (u.includes('/api/student/referral') && !u.includes('invited')) return json({ code: null, invited: 0 });
    if (u.includes('/api/referral/register') && method === 'POST') return json({ ok: false, error: 'audit stub' });
    if (u.includes('/api/student/pending-status')) return json({ pending: false });
    if (u.includes('/api/student/pending-register') && method === 'POST') return json({ ok: false });
    if (u.includes('/api/student/register') && method === 'POST') return json({ ok: false, error: 'stub' });
    if (u.includes('/api/public/groups')) return json({ groups: ['nF-2506'] });
    if (u.includes('/api/game/plays-today')) return json({ plays: 0, limit: 99 });
    if (u.includes('/api/game/record-play') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/game/score') && method === 'POST') return json({ ok: true, new_xp: 200, new_level: 3 });
    if (u.includes('/api/game/leaderboard')) return json({ leaders: [] });
    if (u.includes('/api/game/rooms') && method === 'POST') return json({ room_id: 'r1' });
    if (u.includes('/api/game/rooms/') && u.includes('/join') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/game/rooms/') && u.includes('/progress') && method === 'POST') return json({ ok: true });
    if (u.match(/\/api\/game\/rooms\/[^/?]+$/) && method === 'GET') return json({ ok: true, state: {} });
    if (u.includes('/api/game/rooms?')) return json({ rooms: [] });
    if (u.includes('/api/chat?')) return json({ messages: [] });
    if (u.includes('/api/chat') && method === 'POST') return json({ ok: true, id: 1 });
    return json({});
  });
  await page.route('**/manifest.json', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ name: 'Audit' }) }),
  );
}

async function setupAdminMiniAuditMocks(page) {
  const sampleStudent = {
    user_id: 101,
    full_name: 'Talaba One',
    group_name: 'nF-2506',
    mars_id: 'M001',
    att_today: 'pending',
    avatar: '🎓',
    username: 'stu1',
    phone: '+998900000001',
    last_active: '2026-05-01',
  };
  const sampleGroup = {
    chat_id: -1001,
    name: 'nF-2506',
    group_name: 'nF-2506',
    is_active: true,
    audience: 'student',
    student_count: 12,
  };
  const schedJob = {
    job_id: 'daily_lesson_reminder',
    hour: 20,
    minute: 0,
    default_hour: 20,
    default_minute: 0,
    day_of_week: '',
    default_day_of_week: '',
    is_weekly: false,
  };
  const autoItem = {
    job_id: 'daily_lesson_reminder',
    name: 'Kunlik dars eslatmasi',
    what: 'Test',
    schedule_human: 'Har kuni 20:00',
    frequency_per_day: '1',
    trigger_type: 'cron',
    audience: 'guruhlar',
    editable: true,
    toggle_key: 'AUTO_MSG_GROUPS',
    toggle_enabled: true,
    current_hour: 20,
    current_minute: 0,
    current_dow: '',
    default_hour: 20,
    default_minute: 0,
    default_dow: '',
    is_weekly: false,
  };

  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    const headers = route.request().headers();
    const auth = headers.authorization || '';
    const isBearer = auth.startsWith('Bearer ');
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });

    if (url.includes('/api/mini-admin/login') && method === 'POST') {
      return json({ ok: true, token: 'audit-token', username: 'admin' });
    }
    if (url.includes('/api/mini-admin/logout') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/me')) {
      if (isBearer) return json({ ok: true, user_id: -1 });
      return json({ ok: false, error: 'Unauthorized', code: 'unauthorized' }, 401);
    }
    if (!isBearer) return json({ ok: false, error: 'Unauthorized', code: 'unauthorized' }, 401);

    if (url.includes('/api/admin/profile') && method === 'GET') {
      return json({ ok: true, display_name: 'Audit Admin', avatar_emoji: '👨‍💼', referral_pending: 1 });
    }
    if (url.includes('/api/admin/profile') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/stats')) {
      return json({ ok: true, total_students: 10, today_present: 7, today_absent: 1, today_pending: 2 });
    }
    if (url.includes('/api/admin/warnings')) return json({ ok: true, absent_3days: [], no_homework: [] });
    if (url.includes('/api/admin/weekly-stats')) return json({ days: [] });
    if (url.includes('/api/admin/students')) return json({ students: [sampleStudent] });
    if (url.includes('/api/admin/groups') && !url.includes('detail')) return json({ groups: [sampleGroup] });
    if (url.includes('/api/admin/groups-detail')) return json({ groups: [sampleGroup] });
    if (url.includes('/api/admin/attendance')) {
      return json({ date: '2026-05-01', present: [], absent: [], pending: [sampleStudent] });
    }
    if (url.includes('/api/admin/attendance-update') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/student/leaderboard/global')) return json({ leaders: [] });
    if (url.includes('/api/game/leaderboard')) return json({ leaders: [] });
    if (url.includes('/api/admin/curator-stats')) return json([]);
    if (url.includes('/api/admin/referral-students')) return json({ referrals: [] });
    if (url.includes('/api/admin/reminder-time')) {
      if (method === 'POST') return json({ ok: true });
      return json({ hour: 20, minute: 0 });
    }
    if (url.includes('/api/admin/system-status')) {
      return json({
        ok: true,
        version: 'audit',
        database: true,
        scheduler: { configured: true, running: true, state: 'running', jobs: {} },
        uptime_sec: 1,
      });
    }
    if (url.includes('/api/admin/scheduled-jobs')) {
      if (method === 'POST') return json({ ok: true });
      return json({ jobs: [schedJob] });
    }
    if (url.includes('/api/admin/scheduled-jobs/reset') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/auto-messages-overview')) {
      return json({ master_enabled: true, total: 1, items: [autoItem] });
    }
    if (url.includes('/api/admin/auto-messages/master-toggle') && method === 'POST') {
      return json({ ok: true, master_enabled: true });
    }
    if (url.includes('/api/admin/auto-messages/toggle') && method === 'POST') {
      return json({ ok: true, toggle_key: 'AUTO_MSG_GROUPS', enabled: true });
    }
    if (url.includes('/api/admin/broadcast') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/message-templates')) return json({ templates: [] });
    if (url.includes('/api/admin/audit-logs')) return json({ logs: [] });
    if (url.includes('/api/admin/homework-tasks')) return json({ tasks: [] });
    if (url.includes('/api/admin/hw-schedule')) return json({ groups: [] });
    if (url.includes('/api/admin/send-homework') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/update-homework') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/delete-homework') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/restore-homework') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/homework-task-update') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/homework-task-bulk-update') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/message/student') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/message/group') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/student-move') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/student-delete') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/student-restore') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/deleted-students')) return json({ students: [] });
    if (url.includes('/api/admin/toggle-group') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/refresh-group-chat') && method === 'POST') return json({ ok: true });
    if (url.includes('/api/admin/referral-students/') && url.includes('/approve') && method === 'POST') {
      return json({ ok: true });
    }
    if (url.includes('/api/admin/referral-students/') && url.includes('/reject') && method === 'POST') {
      return json({ ok: true });
    }
    return json({ ok: true });
  });
}

async function setupGamesAuditMocks(page) {
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const method = route.request().method();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });
    if (u.includes('/api/me')) return json({ xp: 150, level: 2, full_name: 'Gamer' });
    if (u.includes('/api/game/plays-today')) return json({});
    if (u.includes('/api/game/record-play') && method === 'POST') {
      return json({ play_count: 0, blocked: false, seconds_left: 0, plays_left: 99 });
    }
    if (u.includes('/api/game/leaderboard')) return json({ leaders: [] });
    if (u.includes('/api/student/progress')) {
      return json({
        xp: 150,
        level: 2,
        level_name: 'Test',
        next_level_xp: 300,
        streak_days: 1,
        attend_count: 1,
        hw_conf_count: 0,
        rank: 1,
        mood_today: null,
        game_best: {},
      });
    }
    if (u.includes('/api/game/score') && method === 'POST') {
      return json({ ok: true, new_xp: 160, new_level: 2, leveled_up: false });
    }
    return json({});
  });
}

/** curator.html — sessiya yo'q */
async function setupCuratorLoggedOutMocks(page) {
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });
    if (u.includes('/api/curator/me')) return json({ logged_in: false });
    return json({}, 404);
  });
}

/** curator.html — kirgan + barcha tablar */
async function setupCuratorLoggedInMocks(page) {
  const st = {
    user_id: 501,
    full_name: 'Cur Stu',
    group_name: 'G-QA',
    mars_id: 'M99',
    username: 'stu',
    phone: '+998901111111',
    last_active: '2026-05-01',
  };
  const chart7 = Array.from({ length: 7 }, (_, i) => ({ pct: 40 + i * 5, label: `K${i + 1}` }));
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const method = route.request().method();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });
    if (u.includes('/api/curator/me')) return json({ logged_in: true, full_name: 'Kurator QA' });
    if (u.includes('/api/curator/login') && method === 'POST') return json({ full_name: 'Kurator QA' });
    if (u.includes('/api/curator/logout') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/curator/all-students')) return json({ students: [st] });
    if (u.includes('/api/curator/dashboard-stats')) {
      return json({ present: 1, absent: 0, pending: 0, homework_done: 0 });
    }
    if (u.includes('/api/curator/attendance')) {
      return json({ date: '2026-05-01', present: [st], absent: [], pending: [] });
    }
    if (u.includes('/api/curator/update-attendance') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/curator/send-message') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/curator/statistics')) {
      return json({
        chart: chart7,
        groups: [{ group: 'G-QA', pct: 75 }],
        top_present: [{ full_name: 'A', group_name: 'G-QA', count: 5 }],
        top_absent: [],
      });
    }
    if (u.includes('/api/curator/parent-groups')) return json({ groups: [] });
    if (u.includes('/api/curator/send-yoqlama') && method === 'POST') return json({ ok: true });
    return json({ ok: true });
  });
}

/** admin.html (to'liq panel) */
async function setupAdminHtmlAuditMocks(page) {
  const st = {
    mars_id: 'M1',
    full_name: 'Admin Stu',
    group_name: 'G1',
    registered: true,
    att_today: 'pending',
    phone: '—',
    username: 'u1',
    last_active: '2026-05-01',
  };
  const grp = { chat_id: -2001, name: 'G1', is_active: true, audience: 'STUDENT', day_type: 'ODD' };
  const autoMsg = {
    groups: true,
    students: true,
    curators: true,
    odd: true,
    even: true,
    leaderboard: true,
    per_group: { G1: true },
    per_curator: {},
    _groups: [{ name: 'G1', audience: 'STUDENT' }],
    _curators: [],
  };
  await page.route('**/api/**', async (route) => {
    const u = route.request().url();
    const method = route.request().method();
    const json = (obj, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(obj) });
    if (u.includes('/api/admin/me')) return json({ display_name: 'QA Admin', ok: true });
    if (u.includes('/api/admin/stats')) {
      return json({
        total_students: 5,
        active_groups: 2,
        today_present: 3,
        today_absent: 1,
        today_pending: 1,
        total_groups: 4,
      });
    }
    if (u.includes('/api/admin/all-students')) return json({ students: [st] });
    if (u.includes('/api/admin/attendance')) {
      return json({ date: '2026-05-01', present: [], absent: [], pending: [st] });
    }
    if (u.includes('/api/admin/groups-detail')) return json({ groups: [grp] });
    if (u.includes('/api/admin/toggle-group') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/admin/auto-msg') && method === 'GET') return json(autoMsg);
    if (u.includes('/api/admin/auto-msg') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/admin/groups')) return json({ groups: [{ name: 'G1', audience: 'STUDENT' }] });
    if (u.includes('/api/admin/curator-stats')) return json([]);
    if (u.includes('/api/admin/auto-msg-preview')) {
      return json({
        weekday: 'Dushanba',
        tomorrow: '03.05.2026',
        day_type: 'ODD',
        send_time: '20:00',
        day_on: true,
        global_on: true,
        will_send: [],
        will_skip: [],
      });
    }
    if (u.includes('/api/admin/reminder-time')) {
      if (method === 'POST') return json({ ok: true });
      return json({ hour: 20, minute: 0 });
    }
    if (u.includes('/api/admin/broadcast') && method === 'POST') return json({ sent: 0, failed: 0 });
    if (u.includes('/api/admin/inactive')) return json({ students: [] });
    if (u.includes('/api/admin/button-stats')) return json({ buttons: [] });
    if (u.includes('/api/admin/test-send') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/admin/delete-message') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/admin/delete-test-messages') && method === 'POST') return json({ ok: true });
    if (u.includes('/api/admin/test-leaderboard') && method === 'POST') return json({ ok: true });
    return json({ ok: true });
  });
}

async function setupGuideSmokeMocks(page) {
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );
}

async function openStudentForAudit(page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('onboarding_done', '1');
    } catch (_) {}
  });
  await setupTelegramAndCdnRoutes(page);
  await setupStudentAuditMocks(page);
  await page.goto('/webapp/student.html', { waitUntil: 'domcontentloaded' });
  await sleep(2800);
}

async function openAdminMiniLoggedIn(page) {
  await page.addInitScript(() => {
    localStorage.setItem('miniAdminToken', 'audit-token');
    localStorage.setItem('miniAdminUser', 'admin');
  });
  await setupTelegramAndCdnRoutes(page);
  await setupAdminMiniAuditMocks(page);
  await page.goto('/webapp/admin-mini.html', { waitUntil: 'domcontentloaded' });
  await sleep(900);
}

module.exports = {
  sleep,
  setupTelegramAndCdnRoutes,
  createAuditBag,
  attachAuditCollectors,
  filterPageErrors,
  filterConsoleErrors,
  assertAuditClean,
  setupStudentAuditMocks,
  setupAdminMiniAuditMocks,
  setupGamesAuditMocks,
  setupCuratorLoggedOutMocks,
  setupCuratorLoggedInMocks,
  setupAdminHtmlAuditMocks,
  setupGuideSmokeMocks,
  openStudentForAudit,
  openAdminMiniLoggedIn,
};
