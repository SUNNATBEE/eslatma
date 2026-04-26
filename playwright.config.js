const path = require('path');
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './e2e-tests',
  timeout: 60000,
  expect: { timeout: 15000 },
  use: {
    headless: true,
    viewport: { width: 390, height: 844 },
    baseURL: 'http://127.0.0.1:9876',
    actionTimeout: 15000,
  },
  webServer: {
    command: 'python -m http.server 9876 --bind 127.0.0.1',
    cwd: __dirname,
    url: 'http://127.0.0.1:9876/webapp/student.html',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
