const path = require('path');
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './e2e-tests',
  timeout: 60000,
  expect: { timeout: 15000 },
  /* Bir python http.server — parallel workerlar ba'zan ERR_CONNECTION_REFUSED beradi */
  workers: parseInt(process.env.PW_WORKERS || '1', 10),
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  use: {
    headless: true,
    viewport: { width: 390, height: 844 },
    baseURL: 'http://127.0.0.1:9876',
    actionTimeout: 15000,
    trace: process.env.PW_TRACE === '1' ? 'on' : 'off',
  },
  webServer: {
    command: 'python -m http.server 9876 --bind 127.0.0.1',
    cwd: __dirname,
    url: 'http://127.0.0.1:9876/webapp/student.html',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
