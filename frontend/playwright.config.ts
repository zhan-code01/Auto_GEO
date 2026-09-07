import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 配置
 * 测试文件放在 frontend/e2e(与依赖同目录,保证 @playwright/test 可解析);
 * 需要后端与种子数据,故默认不纳入 push CI,本地手动运行 npm test。
 */
export default defineConfig({
  testDir: './e2e',

  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,

  reporter: 'html',

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
