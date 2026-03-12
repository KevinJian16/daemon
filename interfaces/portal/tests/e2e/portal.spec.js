import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

const repoRoot = "/Users/kevinjian/daemon";
const resetScript = `${repoRoot}/interfaces/portal/scripts/reset_portal_fixture.py`;

function resetFixture() {
  execFileSync("python3", [resetScript], {
    cwd: repoRoot,
    stdio: "ignore",
  });
}

async function waitForPortal(request) {
  await expect
    .poll(async () => {
      const response = await request.get("/portal-api/sidebar");
      return response.status();
    })
    .toBe(200);
}

test.beforeEach(async ({ request }) => {
  resetFixture();
  await waitForPortal(request);
});

test("sidebar reflects desk and folio workspaces", async ({ page }) => {
  await page.goto("/portal/");

  await expect(page.getByTestId("portal-sidebar")).toBeVisible();
  await expect(page.getByTestId("sidebar-workspace-desk")).toContainText("案头");
  await expect(page.getByTestId("sidebar-workspace-folios")).toContainText("卷宗");
  await expect(page.getByTestId("sidebar-desk-children")).toContainText("散札");
  await expect(page.getByTestId("sidebar-desk-children")).toContainText("Tray");
  await expect(page.getByTestId("sidebar-desk-slip-准备客户回访问题")).toBeVisible();
  await expect(page.getByTestId("sidebar-desk-draft-draft_b2e43d25b2ab")).toBeVisible();
  await expect(page.getByTestId("sidebar-folio-周报推进")).toBeVisible();
  await expect(page.getByTestId("sidebar-folio-晨间巡检摘要")).toBeVisible();
  await expect(page.getByTestId("sidebar-folio-list")).not.toContainText("Tray");

  await page.getByTestId("sidebar-search-input").fill("晨间");
  await expect(page.getByTestId("sidebar-folio-晨间巡检摘要")).toBeVisible();
  await expect(page.getByTestId("sidebar-folio-周报推进")).toBeHidden();
});

test("desk voice sheet opens and closes without leaving dead overlay space", async ({ page }) => {
  await page.goto("/portal/");

  await expect(page.getByTestId("desk-page")).toBeVisible();
  await page.getByTestId("desk-voice-open").click();
  await expect(page.getByTestId("desk-voice-sheet")).toBeVisible();
  await expect(page.getByTestId("desk-voice-sheet-dock-composer-input")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("desk-voice-sheet")).toBeHidden();

  await page.getByTestId("desk-voice-open").click();
  await expect(page.getByTestId("desk-voice-sheet")).toBeVisible();
  await page.getByTestId("desk-voice-sheet").click({ position: { x: 8, y: 8 } });
  await expect(page.getByTestId("desk-voice-sheet")).toBeHidden();
});

test("desk tray can crystallize a draft into a slip", async ({ page }) => {
  await page.goto("/portal/?draft=draft_b2e43d25b2ab");

  await expect(page.getByTestId("desk-tray-card-draft_b2e43d25b2ab")).toBeVisible();
  await expect(page.getByTestId("desk-tray-title-draft_b2e43d25b2ab")).toBeVisible();
  await page.getByTestId("desk-tray-title-draft_b2e43d25b2ab").fill("下周例会问题");
  await page.getByTestId("desk-tray-objective-draft_b2e43d25b2ab").fill("补写下周例会要问的三个问题，并收成一张能继续跟进的札。");
  await page.getByTestId("desk-tray-crystallize-draft_b2e43d25b2ab").click();

  await expect(page).toHaveURL(/\/portal\/slips\//);
  await expect(page.getByTestId("slip-page")).toBeVisible();
  await expect(page.getByRole("heading", { name: "下周例会问题" })).toBeVisible();
});

test("desk organize can merge two loose slips into a new folio", async ({ page }) => {
  await page.goto("/portal/");

  await page.getByTestId("desk-organize-toggle").click();
  await page.getByTestId("desk-slip-card-准备客户回访问题").dragTo(page.getByTestId("desk-slip-card-整理部署检查项"));

  await expect(page).toHaveURL(/\/portal\/folios\//);
  await expect(page.getByTestId("folio-page")).toBeVisible();
  await expect(page.getByRole("heading", { name: /整理部署检查项/ })).toBeVisible();
});

test("folio page shows board, tray, and inline dock", async ({ page }) => {
  await page.goto("/portal/folios/%E5%91%A8%E6%8A%A5%E6%8E%A8%E8%BF%9B");

  await expect(page.getByTestId("folio-page")).toBeVisible();
  await expect(page.getByTestId("folio-board-compact")).toBeVisible();
  await expect(page.getByTestId("folio-tray-section")).toBeVisible();
  await expect(page.getByTestId("folio-dock-composer-input")).toBeVisible();
  await expect(page.getByTestId("folio-voice-open")).toHaveCount(0);

  await page.getByTestId("folio-dock-composer-input").click();
  await expect(page.getByTestId("folio-dock-panel-wrap")).toBeVisible();
  await page.getByRole("heading", { name: "周报推进" }).click();
  await expect(page.getByTestId("folio-dock-panel-wrap")).toBeHidden();

  await page.getByTestId("folio-board-compact-detail").click();
  await expect(page.getByTestId("folio-board-overlay")).toBeVisible();
  await expect(page.getByTestId("folio-board")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("folio-board-overlay")).toBeHidden();
});

test("folio organize regularizes the board into a tighter row layout", async ({ page }) => {
  await page.goto("/portal/folios/%E5%91%A8%E6%8A%A5%E6%8E%A8%E8%BF%9B");

  const firstCard = page.getByTestId("folio-board-compact-card-整理项目周报");
  const secondCard = page.getByTestId("folio-board-compact-card-跟进阻塞项");
  const beforeFirst = await firstCard.boundingBox();
  const beforeSecond = await secondCard.boundingBox();
  expect(beforeFirst).not.toBeNull();
  expect(beforeSecond).not.toBeNull();

  await page.getByTestId("folio-organize-toggle").click();
  await expect(page.getByTestId("folio-return-to-desk-dropzone")).toBeVisible();
  await page.waitForTimeout(360);

  const afterFirst = await firstCard.boundingBox();
  const afterSecond = await secondCard.boundingBox();
  expect(afterFirst).not.toBeNull();
  expect(afterSecond).not.toBeNull();

  expect(Math.abs(afterFirst.y - afterSecond.y)).toBeLessThan(4);
  expect(Math.abs(afterFirst.x - beforeFirst.x) + Math.abs(afterSecond.x - beforeSecond.x)).toBeGreaterThan(12);
});

test("folio organize can adopt a loose desk slip into the folio", async ({ page }) => {
  await page.goto("/portal/folios/%E5%91%A8%E6%8A%A5%E6%8E%A8%E8%BF%9B");

  await page.getByTestId("folio-organize-toggle").click();
  await expect(page.getByTestId("folio-loose-slip-strip")).toBeVisible();
  await page.getByTestId("folio-loose-slip-准备客户回访问题").dragTo(page.getByTestId("folio-board-compact"));

  await expect(page.getByTestId("folio-board-compact-card-准备客户回访问题")).toBeVisible();
});

test("folio organize can take a slip back to the desk", async ({ page }) => {
  await page.goto("/portal/folios/%E5%91%A8%E6%8A%A5%E6%8E%A8%E8%BF%9B");

  await page.getByTestId("folio-organize-toggle").click();
  await page.getByTestId("folio-board-compact-card-整理项目周报").dragTo(page.getByTestId("folio-return-to-desk-dropzone"));
  await expect(page.getByTestId("folio-board-compact-card-整理项目周报")).toBeHidden();

  await page.goto("/portal/");
  await expect(page.getByTestId("desk-slip-card-整理项目周报")).toBeVisible();
});

test("slip deep link expands a closed deed block and shows offering preview", async ({ page }) => {
  await page.goto("/portal/slips/%E6%95%B4%E7%90%86%E9%A1%B9%E7%9B%AE%E5%91%A8%E6%8A%A5/deeds/deed_demo_closed");

  await expect(page.getByTestId("slip-page")).toBeVisible();
  await expect(page.getByTestId("slip-deed-block-deed_demo_closed")).toBeVisible();
  await expect(page.getByTestId("slip-deed-block-deed_demo_closed")).toContainText("report.md");
  await expect(page.getByTestId("slip-deed-block-deed_demo_closed")).toContainText("周报摘要");
});

test("slip unified conversation accepts a message and ArrowUp recalls the last text", async ({ page }) => {
  const messageText = `补一句说明 ${Date.now()}`;
  await page.goto("/portal/slips/%E8%B7%9F%E8%BF%9B%E9%98%BB%E5%A1%9E%E9%A1%B9");

  await page.getByTestId("slip-dock-composer-input").click();
  await expect(page.getByTestId("slip-dock-panel-wrap")).toBeVisible();
  await page.getByTestId("slip-dock-composer-input").fill(messageText);
  await page.getByTestId("slip-dock-composer-submit").click();

  await expect(page.getByText(messageText)).toBeVisible();
  await expect(page.getByTestId("slip-dock-composer-input")).toHaveValue("");

  await page.getByTestId("slip-dock-composer-input").focus();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("slip-dock-composer-input")).toHaveValue(messageText);
});

test("running slip can open move full view and deep link to its active deed block", async ({ page }) => {
  await page.goto("/portal/slips/%E8%B7%9F%E8%BF%9B%E9%98%BB%E5%A1%9E%E9%A1%B9/deeds/deed_demo_running");

  await expect(page.getByTestId("slip-page")).toBeVisible();
  await expect(page.getByTestId("slip-deed-block-deed_demo_running")).toBeVisible();
  await expect(page.getByTestId("slip-deed-pause-deed_demo_running")).toBeVisible();

  await page.getByTestId("slip-move-detail").click();
  await expect(page.getByTestId("slip-move-overlay")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("slip-move-overlay")).toBeHidden();
});
