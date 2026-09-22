// The Finish watchdog (DESIGN_gym_logger.md §4), which only a browser can show: Telegram closes
// the app when it takes the log, so a page still open afterwards means the log never left.
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import { freePort, servePage } from "./serve.mjs";

// A Telegram client that answers every call and then does nothing with the log.
const STUB_TELEGRAM = () => {
  window.__sent = [];
  window.Telegram = {
    WebApp: {
      platform: "android",
      initData: "",
      isVersionAtLeast: () => false,
      ready: () => {},
      expand: () => {},
      showAlert: (message) => { window.__alert = message; },
      MainButton: {
        setText: () => {},
        show: () => {},
        onClick: (handler) => { window.__finish = handler; },
      },
      sendData: (text) => { window.__sent.push(text); },
    },
  };
};

async function browser() {
  // Playwright and Chromium are not part of the page; without them there is nothing to run.
  try {
    const { chromium } = await import("playwright");
    return await chromium.launch({ executablePath: "/snap/bin/chromium", headless: true });
  } catch (problem) {
    return null;
  }
}

test("a log Telegram does not take comes back as a sheet to copy", async (t) => {
  const engine = await browser();
  if (!engine) {
    t.skip("playwright or chromium is missing");
    return;
  }
  const port = await freePort();
  const server = await servePage(port);
  try {
    const page = await (await engine.newContext({ viewport: { width: 390, height: 844 } }))
      .newPage();
    // The real script would replace the stub, and it is not needed to drive the page.
    await page.route("**/telegram-web-app.js", (route) => route.abort());
    await page.addInitScript(STUB_TELEGRAM);
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");

    // Inside Telegram, Finish is the app's own bottom button and the page's one is hidden.
    assert.equal(await page.locator("#finish").isVisible(), false);
    await page.locator(".card").first().locator(".set")
      .nth(0)
      .locator(".tick")
      .click();
    await page.evaluate(() => window.__finish());

    // The log reaches Telegram, and the sheet is not up yet.
    const sent = await page.evaluate(() => window.__sent);
    assert.equal(sent.length, 1);
    assert.equal(JSON.parse(sent[0]).x[0].n, "belt squat");
    assert.equal(await page.locator("#output-sheet").isVisible(), false);

    // The app is still open after the watchdog, so the athlete is given the log to copy.
    await page.waitForSelector("#output-sheet:not([hidden])", { timeout: 4000 });
    assert.equal(await page.locator("#output-hint").textContent(),
                 "Telegram did not take the log. Copy it and send it to the bot as a message.");
    assert.equal(await page.locator("#output-text").inputValue(), sent[0]);
  } finally {
    await engine.close();
    server.kill();
  }
});
