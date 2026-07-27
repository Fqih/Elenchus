/**
 * Studio frontend E2E smoke test (Phase 6 acceptance).
 *
 * Boots the FastAPI server with the real NLI model, builds the React
 * frontend, runs the Playwright assertion script, and prints the result.
 * Exit 0 if all assertions pass, 1 otherwise.
 *
 * Usage (from the repo root):
 *
 *   cd studio/frontend && npm install && npx playwright install chromium
 *   cd ../.. && npm create --prefix studio/frontend vite@latest -- --template react-ts studio/frontend  # already done
 *   tsx studio/examples/studio_frontend_smoke_test.ts
 */
import { execSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 8765;
const dbPath = mkdtempSync(join(tmpdir(), "studio-e2e-")) + "/db.sqlite";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForServer(url: string, timeoutMs: number) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return;
    } catch {
      // not yet
    }
    await sleep(500);
  }
  throw new Error(`server did not become ready at ${url} within ${timeoutMs}ms`);
}

async function main() {
  // 1. Build the frontend.
  console.log("[1/4] building frontend…");
  execSync("npm run build", {
    cwd: "studio/frontend",
    stdio: "inherit",
  });

  // 2. Start FastAPI with the built static files.
  console.log("[2/4] starting FastAPI server…");
  const server = spawn(
    "python",
    [
      "-m",
      "studio.api.server",
      "--db",
      dbPath,
      "--host",
      "127.0.0.1",
      "--port",
      String(PORT),
    ],
    {
      env: {
        ...process.env,
        LD_LIBRARY_PATH: (process.env.LD_LIBRARY_PATH ?? "") + ":" + `${process.env.HOME}/.local/lib`,
      },
      stdio: "inherit",
    },
  );

  try {
    await waitForServer(`http://127.0.0.1:${PORT}/api/projects`, 180_000);
    console.log("[3/4] server ready");

    // 3. Run the Playwright test.
    console.log("[4/4] running Playwright spec…");
    execSync("npx playwright test", {
      cwd: "studio/frontend",
      stdio: "inherit",
    });

    console.log("all acceptance checks passed");
  } finally {
    server.kill();
    rmSync(dbPath, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
