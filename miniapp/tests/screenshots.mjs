// Phone-sized screenshots of the gym logger, to see it the way the athlete does
// (DESIGN_gym_logger.md §1). It serves `miniapp/` itself and shuts the server down after.
//
//   ln -s /usr/share/nodejs miniapp/tests/node_modules
//   SHOTS_DIR=/tmp/shots NODE_PATH=/usr/share/nodejs node miniapp/tests/screenshots.mjs
//
// Chromium only: Firefox does not launch in this environment.
import fs from "node:fs";
import path from "node:path";

import { chromium } from "playwright";

import { freePort, servePage } from "./serve.mjs";

const SHOTS = process.env.SHOTS_DIR || path.join(process.env.TMPDIR || "/tmp", "gym-shots");
const PHONE = { width: 390, height: 844 };

async function shoot(page, name) {
  await page.screenshot({ path: path.join(SHOTS, name) });
  console.log(`  ${path.join(SHOTS, name)}`);
}

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  const port = await freePort();
  const server = await servePage(port);
  const browser = await chromium.launch({ executablePath: "/snap/bin/chromium", headless: true });
  const complaints = [];
  try {
    const context = await browser.newContext({ viewport: PHONE, deviceScaleFactor: 2,
                                               isMobile: true, hasTouch: true });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") {
        complaints.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (problem) => complaints.push(`pageerror: ${problem.message}`));
    page.on("requestfailed", (request) =>
      complaints.push(`requestfailed: ${request.url()} ${request.failure()?.errorText}`));

    // 1. The bare URL, which shows the demo session (§2).
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    await shoot(page, "01-load.png");
    await page.screenshot({ path: path.join(SHOTS, "01-load-full.png"), fullPage: true });

    // 2. Two sets ticked and a load edited by hand.
    const first = page.locator(".card").first();
    await first.locator(".set").nth(0).locator(".tick").click();
    await first.locator(".set").nth(1).locator(".tick").click();
    const kg = first.locator(".set").nth(2).locator(".num").nth(1);
    await kg.fill("145");
    await kg.press("Enter");
    await shoot(page, "02-ticked.png");

    // 3. The swap search, filtered to the card's own movement pattern (§1).
    await first.getByText("Swap").click();
    await page.waitForSelector("#search-sheet:not([hidden])");
    await shoot(page, "03-swap.png");
    await page.locator("#search-close").click();

    // 4. The session's own actions at the foot of the page.
    await page.locator("#add-exercise").scrollIntoViewIfNeeded();
    await shoot(page, "04-foot.png");

    // 5. Finish outside Telegram, which shows the §4 log to copy.
    await page.locator("#finish").click();
    await page.waitForSelector("#output-sheet:not([hidden])");
    await shoot(page, "05-finish.png");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    console.log(`horizontal overflow: ${overflow}px`);
    const log = await page.locator("#output-text").inputValue();
    console.log(`log: ${log}`);

    // 6. The same page in a dark browser, where the Telegram theme variables are absent.
    const dark = await browser.newContext({ viewport: PHONE, deviceScaleFactor: 2,
                                            colorScheme: "dark" });
    const nightPage = await dark.newPage();
    await nightPage.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
    await nightPage.waitForSelector(".card");
    await nightPage.locator(".card").first().locator(".set")
      .nth(0).locator(".tick")
      .click();
    await shoot(nightPage, "06-dark.png");
  } finally {
    await browser.close();
    server.kill();
  }
  console.log(complaints.length ? `console:\n  ${complaints.join("\n  ")}` : "console: clean");
}

main().catch((problem) => {
  console.error(problem);
  process.exitCode = 1;
});
