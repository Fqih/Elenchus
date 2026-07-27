import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    headless: true,
    baseURL: "http://localhost:8765",
  },
  reporter: "list",
});
