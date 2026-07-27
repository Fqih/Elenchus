import { test, expect } from "@playwright/test";

test("phase 6 acceptance: paste source, paste answer, see flagged claim", async ({
  page,
}) => {
  test.setTimeout(180_000);

  await page.goto("/");

  // Create a project.
  await page.getByLabel("Project name").fill("e2e-kb");
  await page.getByRole("button", { name: /create project/i }).click();
  await expect(page.getByText("e2e-kb")).toBeVisible();

  // Open the project.
  await page.getByText("e2e-kb").click();

  // Wait for the project page.
  await expect(page.getByRole("heading", { name: /e2e-kb/i })).toBeVisible();

  // Add a source doc.
  await page.getByLabel("Source name").fill("shipping-faq");
  await page.getByLabel("Source content").fill(
    "Standard shipping takes 3 to 5 business days within the continental United States.",
  );
  await page.getByRole("button", { name: /add source doc/i }).click();
  await expect(page.getByText("v1")).toBeVisible();

  // Submit a deliberately-wrong answer.
  await page.getByLabel("Candidate answer").fill(
    "Standard shipping takes 1 to 2 business days within the continental United States.",
  );
  await page.getByRole("button", { name: /submit check/i }).click();

  // Wait for the mutation to complete: the gate badge appears inside the
  // run-result once the result section renders. This also implicitly covers
  // the F-03 gate-badge-text assertion. NLI is slow on first cold start, so
  // give it a generous timeout.
  const gateBadge = page.locator(".run-result .gate-badge", { hasText: "blocked" });
  await expect(gateBadge).toBeVisible({ timeout: 120_000 });

  // The contradicted claim should appear with the right class inside the
  // run-result. Locate by class so we don't get fooled by the textarea that
  // mirrors the same text in the candidate-answer form.
  const contradictedClaim = page.locator(
    ".run-result .claim-contradicted",
    { hasText: "Standard shipping takes 1 to 2 business days" },
  );
  await expect(contradictedClaim).toBeVisible({ timeout: 60_000 });
  await expect(contradictedClaim).toHaveClass(/claim-contradicted/);

  // F-03 (1): gate badge reads "blocked".
  await expect(gateBadge).toContainText(/blocked/i);

  // F-03 (2): click the claim — evidence panel opens with the excerpt.
  await contradictedClaim.click();
  await expect(
    page.locator(".evidence-panel .evidence-excerpt", {
      hasText: /3 to 5 business days/i,
    }),
  ).toBeVisible();

  // Close the panel.
  await page.getByRole("button", { name: /close/i }).click();

  // F-03 (3): run history shows the run with the gate badge AND a latency
  // value (~500 ms). The history list-item header carries the gate badge +
  // a "<n> ms" latency span.
  const runHistoryHeading = page.getByRole("heading", { name: /run history/i });
  await expect(runHistoryHeading).toBeVisible();

  // Scope to the Run history section (the section whose <h2> says
  // "Run history"). SourceDocList also uses .list .list-item, so a bare
  // ".list .list-item" selector would grab the source-doc preview first.
  const runHistorySection = page.locator("section.section", {
    has: page.getByRole("heading", { name: /run history/i }),
  });
  const firstHistoryItem = runHistorySection
    .locator(".list .list-item[role='button']")
    .first();
  await expect(firstHistoryItem).toBeVisible();
  await expect(firstHistoryItem.locator(".gate-badge")).toBeVisible();
  await expect(firstHistoryItem).toContainText(/\d+\s*ms/);
});
