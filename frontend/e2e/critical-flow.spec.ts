import { expect, test, type Page } from "@playwright/test";

// Critical flow: applicant sees a rule score, runs a What-If and a target plan;
// lender filters candidates, sends an offer; applicant accepts it and the lender sees contact details.

const errors: string[] = [];
function watch(page: Page) {
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
}

async function demoLogin(page: Page, label: RegExp) {
  await page.goto("/login");
  await page.getByRole("button", { name: label }).first().click();
}

test("applicant: score, factors, what-if, target, report", async ({ page }) => {
  watch(page);
  await demoLogin(page, /Moderate/);
  await expect(page.getByText("Rule-Based Policy Decision").first()).toBeVisible();
  const score = await page.locator(".hero-score svg text").first().textContent();
  expect(Number(score)).toBeGreaterThan(0);

  await page.getByRole("link", { name: "Score details" }).click();
  await expect(page.getByText("Employment Stability").first()).toBeVisible();
  await page.getByRole("tab", { name: "Score trace" }).click();
  await expect(page.getByText(/Final: \d+ \/ 1000/)).toBeVisible();
  await page.getByRole("tab", { name: "ML validation" }).click();
  await expect(page.getByText("ML Risk Score").first()).toBeVisible();

  await page.getByRole("link", { name: "What-If" }).click();
  await page.getByRole("button", { name: "Simulate for me" }).nth(3).click(); // delinquency preset
  await expect(page.locator("#sim-result")).toBeVisible();
  await expect(page.locator("#sim-result").getByText("Nothing was saved to your history")).toBeVisible();

  await page.getByRole("link", { name: "Target" }).click();
  await page.getByRole("button", { name: "Find my plan" }).click();
  await expect(page.locator(".card-head .badge").filter({ hasText: /reachable|already eligible|blocked/i })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByText("Score history")).toBeVisible();
  await page.getByRole("link", { name: "Report" }).click();
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download PDF" }).click();
  expect((await dl).suggestedFilename()).toMatch(/\.pdf$/);
  expect(errors).toEqual([]);
});

test("lender offer -> applicant accepts -> contact revealed -> bank application", async ({ browser }) => {
  const lender = await (await browser.newContext()).newPage();
  watch(lender);
  await demoLogin(lender, /Pinewood/);
  await expect(lender.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  // candidate list is anonymised and filterable
  await lender.goto("/lender/candidates?eligible_for=P_03&score_min=650");
  await expect(lender.locator("tbody tr.clickable").first()).toBeVisible();

  // the borderline demo applicant qualifies for Pinewood's Standard Credit Card (min 650)
  const applicant = await (await browser.newContext()).newPage();
  watch(applicant);
  await demoLogin(applicant, /Borderline/);
  await expect(applicant.getByText("Rule-Based Policy Decision").first()).toBeVisible();
  const uid = await applicant.evaluate(() => JSON.parse(sessionStorage.getItem("altcredit.session")!).user_id);

  await lender.goto(`/lender/candidates/${uid}`);
  const send = lender.getByRole("button", { name: "Send offer" });
  await expect(send).toBeEnabled();
  await send.click();
  await lender.getByRole("dialog").getByRole("button", { name: "Send offer" }).click();
  // a second open offer for the same product is refused, which is also correct on re-runs
  await expect(lender.getByText(/Offer sent|open offer for this product already exists/).first()).toBeVisible();
  await lender.keyboard.press("Escape");

  await applicant.getByRole("link", { name: "Offers" }).click();
  const card = applicant.locator(".card").filter({ hasText: "Pinewood" }).filter({ has: applicant.getByRole("button", { name: "Accept" }) }).first();
  await card.getByRole("button", { name: "Accept" }).click();
  await applicant.getByRole("button", { name: "Accept and share my contact" }).click();
  await expect(applicant.getByRole("button", { name: "Apply with the bank" }).first()).toBeVisible();

  await lender.goto(`/lender/candidates/${uid}`);
  await expect(lender.getByText("Contact details unlock")).toHaveCount(0);
  await expect(lender.locator("h1")).not.toContainText("*");

  await applicant.getByRole("button", { name: "Apply with the bank" }).first().click();
  await expect(applicant.getByRole("heading", { name: "Bank applications" })).toBeVisible();
  await expect(applicant.locator("tbody tr").first()).toContainText(/SUBMITTED|UNDER REVIEW|APPROVED|MANUAL REVIEW|DECLINED/);
  await applicant.getByRole("button", { name: "Check status" }).first().click();
  expect(errors).toEqual([]);
});
