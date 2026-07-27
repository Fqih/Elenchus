import { test, expect } from "@playwright/test";

test("phase 6 acceptance: paste source, paste answer, see flagged claim", async ({
  page,
}) => {
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

  // The contradicted claim should appear with the right class.
  await expect(page.getByText("Standard shipping takes 1 to 2 business days within the continental United States."))
    .toHaveClass(/claim-contradicted/);

  // The gate badge should read "blocked".
  await expect(page.getByText("blocked").first()).toBeVisible();

  // Click the claim — evidence panel opens.
  await page.getByText("Standard shipping takes 1 to 2 business days within the continental United States.").click();
  await expect(page.getByText(/3 to 5 business days/i)).toBeVisible();

  // Close the panel.
  await page.getByRole("button", { name: /close/i }).click();

  // Run history shows the run.
  await expect(page.getByText("Run history")).toBeVisible();
});
