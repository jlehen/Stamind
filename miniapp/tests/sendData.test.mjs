// What only a browser can show. The Finish watchdog (DESIGN_gym_logger.md §4): Telegram closes
// the app when it takes the log, so a page still open afterwards means the log never left. And
// a past log opened from the calendar's day sheet (§8).
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
        show: () => { window.__mainButton = true; },
        hide: () => { window.__mainButton = false; },
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

// Runs `drive(page, site)` on a phone-sized page inside the stub Telegram, with `miniapp/`
// served at `site`.
async function onPhone(t, drive) {
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
    await drive(page, `http://127.0.0.1:${port}`);
  } finally {
    await engine.close();
    server.kill();
  }
}

test("a log Telegram does not take comes back as a sheet to copy", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
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
    assert.equal(JSON.parse(sent[0]).x[0].n, "SQUAT/BELT_SQUAT");
    assert.equal(await page.locator("#output-sheet").isVisible(), false);

    // The app is still open after the watchdog, so the athlete is given the log to copy.
    await page.waitForSelector("#output-sheet:not([hidden])", { timeout: 4000 });
    assert.match(await page.locator("#output-hint").textContent(), /Tap Retry/);
    assert.equal(await page.locator("#output-text").inputValue(), sent[0]);

    // Retry sends the same log again, since the bot keeps only the last one.
    await page.locator("#output-retry").click();
    assert.deepEqual(await page.evaluate(() => window.__sent), [sent[0], sent[0]]);
  });
});

// Thursday 24 September as its month's file brings it: the sheet, and the gym log beside its
// session. The curls were added, the leg press stood for the squat, the pull-ups were not done.
const LOGGED_DAY = {
  x: [{ i: "🏋️", g: "ok" }],
  u: [],
  c: 0,
  s: 0,
  sheet: [["Done", ["✅ 🏋️ Gym: lower body strength — 60 min"]]],
  gym: {
    s: {
      v: 2,
      r: 727,
      d: "2026-09-24",
      t: "Gym: lower body strength",
      x: [{ n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 },
          { n: "PULL_UP/PULL_UP", s: 3, lo: 6, hi: 8, kg: null }],
      notes: "",
    },
    l: {
      v: 2,
      r: 727,
      d: "2026-09-24",
      st: "18:02",
      en: "19:05",
      x: [{ n: "CURL/BARBELL_BICEPS_CURL", sets: [[10, 30, 60]] },
          { n: "SQUAT/LEG_PRESS", p: 1, sets: [[5, 120, 200], [6, 140, 400]] }],
    },
  },
};

const CALENDAR = {
  v: 1,
  at: "2026-09-25T07:02",
  today: "2026-09-25",
  from: "2026-08-28",
  to: "2026-11-06",
  goal: null,
  goals: [],
  meso: [],
  fit: ["2026-08-28", "2026-11-06"],
  days: { "2026-09-24": LOGGED_DAY },
};

async function packed(snapshot) {
  // As `calendar_page.pack` writes the button's data: zlib, then base64url.
  const bytes = new TextEncoder().encode(JSON.stringify(snapshot));
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate"));
  return Buffer.from(await new Response(stream).arrayBuffer()).toString("base64url");
}

test("a gym log opens from the calendar locked, and Edit lets it be sent again", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/calendar.html#c=${await packed(CALENDAR)}`,
                    { waitUntil: "networkidle" });
    await page.locator(".cell:has(.num:text-is('24'))").click();
    await page.getByText("Open the gym log").click();
    await page.waitForSelector(".card");
    assert.match(page.url(), /index\.html#s=/);

    // Locked: the sets as done, no stepper, no bottom button, and a tick that does nothing.
    // The log holds keys, and the cards show their words (DESIGN_exercise_table.md §8).
    assert.deepEqual(await page.locator(".card-title").allTextContents(),
                     ["[Curl] Barbell biceps curl", "[Squat] Leg press", "Pull up"]);
    assert.equal(await page.locator("#tally").textContent(), "· 3 sets done");
    assert.match(await page.locator("#opened-note").textContent(), /Tap Edit/);
    assert.equal(await page.locator(".step").first().isVisible(), false);
    assert.equal(await page.locator("#reset").isVisible(), false);
    assert.equal(await page.evaluate(() => window.__mainButton), false);
    await page.locator(".tick").first().click({ force: true });
    assert.equal(await page.locator("#tally").textContent(), "· 3 sets done");

    // Edit unlocks the cards and brings the bottom button back; the log keeps its day.
    await page.locator("#edit").click();
    assert.equal(await page.evaluate(() => window.__mainButton), true);
    await page.locator(".card").first().locator(".set").first().locator(".step")
      .last()
      .click();
    await page.evaluate(() => window.__finish());
    const sent = JSON.parse((await page.evaluate(() => window.__sent))[0]);
    assert.deepEqual([sent.d, sent.st, sent.en], ["2026-09-24", "18:02", "19:05"]);
    assert.deepEqual(sent.x[0].sets, [[10, 32.5, 60]]);
    assert.deepEqual(sent.x[1], LOGGED_DAY.gym.l.x[1]);

    // Lock puts the cards out of reach again, and Back returns to the calendar.
    await page.locator("#edit").click();
    assert.equal(await page.locator(".step").first().isVisible(), false);
    await page.locator("#back").click();
    await page.waitForURL(/calendar\.html/);
  });
});
