const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './e2e-tests',
  timeout: 30000,
  use: {
    headless: true,
    viewport: { width: 390, height: 844 }, // iPhone 14 Pro
  },
});
