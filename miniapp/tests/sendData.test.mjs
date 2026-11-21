// What only a browser can show. The Finish watchdog (DESIGN_gym_logger.md §4): Telegram closes
// the app when it takes the log, so a page still open afterwards means the log never left. And
// a past log opened from the calendar's day sheet (§8), and the plan page's deload row.
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../logic.js";
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

test("the Order sheet makes two tapped exercises trade places", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    const names = () => page.locator(".card .chip").allTextContents();
    const before = await names();

    // The sheet covers the page, so Telegram's bottom button hides under it.
    await page.locator("#order").click();
    assert.equal(await page.evaluate(() => window.__mainButton), false);
    const rows = page.locator("#order-rows .order-row");
    assert.equal(await rows.count(), before.length);
    // The belt squat's line shows its heaviest load, not its warm-up's.
    assert.equal(await rows.nth(0).locator(".order-load").textContent(), "140 kg");

    // A tap on the picked line lets it go; two different lines trade places.
    await rows.nth(0).click();
    await rows.nth(0).click();
    assert.deepEqual(await names(), before);
    await rows.nth(0).click();
    await rows.nth(3).click();
    const after = await names();
    assert.equal(after[0], before[3]);
    assert.equal(after[3], before[0]);
    assert.equal(await page.locator("#order-rows .swapped").count(), 2);

    // One swap is one Undo step.
    await page.locator("#order-close").click();
    assert.equal(await page.evaluate(() => window.__mainButton), true);
    await page.locator("#undo").click();
    assert.deepEqual(await names(), before);
  });
});

test("the Order sheet's Move above puts the first tapped exercise above the second", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    const names = () => page.locator(".card .chip").allTextContents();
    const before = await names();
    const rows = page.locator("#order-rows .order-row");

    // The end line shows only under Move above, once a line is picked.
    await page.locator("#order").click();
    await rows.nth(0).click();
    assert.equal(await page.locator("#order-end").isVisible(), false);
    await page.locator("#order-move").click();
    assert.equal(await page.locator("#order-rows .picked").count(), 0);
    assert.match(await page.locator("#order-hint").textContent(), /goes above/);

    // The fourth exercise goes above the first; the others keep their order.
    await rows.nth(3).click();
    assert.equal(await page.locator("#order-end").isVisible(), true);
    await rows.nth(0).click();
    assert.deepEqual((await names()).slice(0, 4), [before[3], before[0], before[1], before[2]]);
    assert.equal(await page.locator("#order-rows .swapped").count(), 1);

    // The first line goes to the end, and one Undo step takes that back.
    await rows.nth(0).click();
    await page.locator("#order-end").click();
    const moved = await names();
    assert.equal(moved[moved.length - 1], before[3]);

    // A reopened sheet is back on Trade places.
    await page.locator("#order-close").click();
    await page.locator("#undo").click();
    assert.deepEqual((await names()).slice(0, 4), [before[3], before[0], before[1], before[2]]);
    await page.locator("#order").click();
    assert.equal(await page.locator("#order-trade").getAttribute("aria-pressed"), "true");
  });
});

// The demo session writes the belt squat as 1×5 @ 120, then 3×4–6 @ 140: one card (§1).
test("a warm-up and its main sets are one card, each row's mark a warm-up switch", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    const card = page.locator(".card").first();
    const marks = () => card.locator(".mark").allTextContents();
    assert.equal(await card.locator(".card-pres").textContent(), "1×5 @ 120 kg, 3×4–6 @ 140 kg");
    assert.deepEqual(await marks(), ["W", "1", "2", "3"]);

    // A warm-up row goes under the warm-up; a tap on a main row's mark makes it a warm-up.
    await card.getByRole("button", { name: "Add a warm-up set" }).click();
    assert.deepEqual(await marks(), ["W", "W", "1", "2", "3"]);
    await card.locator(".mark").nth(2).click();
    assert.deepEqual(await marks(), ["W", "W", "W", "1", "2"]);

    // The card's ↶ takes back one change at a time.
    await card.locator(".pill.undo").click();
    assert.deepEqual(await marks(), ["W", "W", "1", "2", "3"]);
  });
});

// Each of the two split pills is one cell: its left half takes a row away, its right half adds
// one, and a tap on the word over them lands on the half under it (§1).
test("the split pills' halves add and remove main and warm-up rows", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    const card = page.locator(".card").first();
    const marks = () => card.locator(".mark").allTextContents();
    const tap = async (pill, side) => {
      const cell = card.locator(".split").nth(pill);
      const box = await cell.boundingBox();
      // Just off the middle, so the tap lands on the word as well as on the half.
      const x = side === "left" ? box.width * 0.4 : box.width * 0.6;
      await cell.click({ position: { x, y: box.height / 2 } });
    };
    assert.deepEqual(await card.locator(".split").allTextContents(), ["−+Set", "−+W Set"]);
    await tap(0, "right");
    assert.deepEqual(await marks(), ["W", "1", "2", "3", "4"]);
    await tap(0, "left");
    assert.deepEqual(await marks(), ["W", "1", "2", "3"]);
    await tap(1, "right");
    assert.deepEqual(await marks(), ["W", "W", "1", "2", "3"]);
    await tap(1, "left");
    await tap(1, "left");
    assert.deepEqual(await marks(), ["1", "2", "3"]);
    // With no warm-up row left, the left half of the warm-up pill does nothing.
    await tap(1, "left");
    assert.deepEqual(await marks(), ["1", "2", "3"]);
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
    // The log holds keys, and the cards show their words (DESIGN_exercise_table.md §8) after
    // the icon of their body region (§3.9).
    assert.deepEqual(await page.locator(".card-title").allTextContents(),
                     ["💪 [Curl] Barbell biceps curl", "🦵 [Squat] Leg press", "💪 Pull up"]);
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

// Wednesday 4 November, inside a deload (DESIGN_deload_weeks.md §11.1).
test("the plan page's deload row cannot be tapped, and its rail is dashed", async (t) => {
  const snapshot = { v: 1, at: "2026-11-04T07:02", today: "2026-11-04", goals: [],
                     meso: [{ n: "Build", s: "2026-10-19", e: "2026-11-08", d: "2026-11-02" },
                            { n: "Peak", s: "2026-11-09", e: "2026-11-29" }] };
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/plan.html#c=${await packed(snapshot)}`, { waitUntil: "networkidle" });
    const row = page.locator(".plan-deload");
    assert.equal(await row.textContent(), "🔋 Deload · 2 Nov – 8 Nov");
    assert.equal(await row.locator("button").count(), 0);
    await row.click();
    assert.equal(await page.locator("#row-sheet").isVisible(), false);

    // Tapping a mesocycle opens its sheet with no chat fallback button underneath.
    await page.locator(".plan-row").first().click();
    assert.equal(await page.locator("#row-sheet").isVisible(), true);
    assert.equal(await page.locator("#sheet-body button").count(), 0);

    // The deload's row and today's are dashed; the two mesocycles' rows are not.
    assert.equal(await page.locator(".rail").count(), 4);
    const rail = page.locator(".plan-deload .rail");
    assert.match(await rail.getAttribute("class"), /\bdeload\b/);
    assert.equal(await page.locator(".rail.deload").count(), 2);
    const mask = await rail.evaluate((node) => getComputedStyle(node).maskImage);
    assert.match(mask, /repeating-linear-gradient/);
    assert.doesNotMatch(mask, /90deg/);
  });
});

// The athlete leaves the app between two sets, and Telegram loads the page again when they come
// back. The exercises' file is slow on the gym's signal: the clock is back before it (§1).
test("a reopened page shows the running clock before the exercises arrive", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    await page.locator("#start-clock").click();

    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await page.route("**/exercises.json*", async (route) => {
      await held;
      await route.continue();
    });
    await page.reload();
    await page.waitForSelector("#rest:not([hidden])");
    assert.equal(await page.locator("#start-clock").isVisible(), false);
    assert.equal(await page.locator("#rest-label").textContent(), "since start");
    assert.equal(await page.locator(".card").count(), 0);

    release();
    await page.waitForSelector(".card");
  });
});

test("a Finish tapped by mistake can be resumed, and the next Finish sends again", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    // Telegram's bottom button is not covered by a sheet, so it hides while the search is up.
    assert.equal(await page.evaluate(() => window.__mainButton), true);
    await page.locator(".card").first().locator(".replace").click();
    assert.equal(await page.evaluate(() => window.__mainButton), false);
    await page.locator("#search-close").click();
    assert.equal(await page.evaluate(() => window.__mainButton), true);

    await page.locator(".card").first().locator(".set").nth(0).locator(".tick").click();
    assert.equal(await page.locator("#resume-clock").isVisible(), false);
    await page.evaluate(() => window.__finish());

    // Telegram closed the page; the athlete opens it again from the same button.
    await page.reload();
    await page.waitForSelector(".card");
    assert.equal(await page.locator("#rest-label").textContent(), "in total");
    assert.equal(await page.locator("#reset-clock").isVisible(), false);
    await page.locator("#resume-clock").click();

    assert.equal(await page.locator("#rest-label").textContent(), "since last set");
    assert.equal(await page.locator("#resume-clock").isVisible(), false);
    assert.equal(await page.locator("#reset-clock").isVisible(), true);
    assert.equal(await page.locator("#sent").isVisible(), false);
    await page.evaluate(() => window.__finish());
    assert.equal((await page.evaluate(() => window.__sent)).length, 1);
  });
});

// It is Monday. The coach rewrote the session after the athlete's button was built, so the
// button the bot sends with the log's summary carries the newer revision (§1).
test("a page reopened on a newer revision of the day shows the log already sent", async (t) => {
  await onPhone(t, async (page, site) => {
    await page.goto(`${site}/`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card");
    await page.locator(".card").first().locator(".set").nth(0).locator(".tick").click();
    await page.evaluate(() => window.__finish());

    const rewritten = { ...logic.demoSession(), r: 1 };
    await page.goto(`${site}/index.html#s=${logic.encodeSession(rewritten)}`);
    // A new hash alone keeps the page; Telegram loads it afresh.
    await page.reload();
    await page.waitForSelector(".card");
    assert.equal(await page.locator("#sent").isVisible(), true);
  });
});

// A bench press, whose exercise has photos, and a split squat, whose exercise has none.
const TWO_CARDS = {
  ...logic.demoSession(),
  d: "2026-11-16",
  t: "Gym: upper and legs",
  notes: "",
  x: [{ n: "BENCH_PRESS/BENCH_PRESS", s: 3, lo: 6, hi: 8, kg: 65 },
      { n: "LUNGE/DUMBBELL_BULGARIAN_SPLIT_SQUAT", s: 3, lo: 6, hi: 8, kg: 35 }],
};

async function openTwoCards(page, site) {
  // The photos come from GitHub, which a test does not reach.
  await page.route("**/raw.githubusercontent.com/**", (route) => route.abort());
  await page.goto(`${site}/index.html#s=${logic.encodeSession(TWO_CARDS)}`,
                  { waitUntil: "networkidle" });
  await page.waitForSelector(".card");
}

// It is Tuesday. The athlete reaches for the bench press's ↓ and touches its ✕ (§1).
test("a card's ✕ deletes on the second tap, and a tap elsewhere lets it go", async (t) => {
  await onPhone(t, async (page, site) => {
    await openTwoCards(page, site);
    const names = () => page.locator(".card .chip").allTextContents();
    const before = await names();
    const del = page.locator(".card").first().locator(".del");
    const other = page.locator(".card").nth(1).locator(".del");

    // The first tap arms it and deletes nothing.
    await del.click();
    assert.match(await del.getAttribute("class"), /\barmed\b/);
    assert.equal(await del.getAttribute("aria-label"), "Tap again to delete Bench press");
    assert.deepEqual(await names(), before);

    // A tap in a number box lets it go, and the box keeps its focus and what is typed: the
    // cards were not drawn again.
    const reps = page.locator(".card").nth(1).locator(".num").first();
    await reps.click();
    await reps.pressSequentially("9");
    assert.doesNotMatch(await del.getAttribute("class"), /\barmed\b/);
    assert.equal(await del.getAttribute("aria-label"), "Delete Bench press");
    assert.equal(await reps.evaluate((field) => field === document.activeElement), true);
    assert.equal(await reps.inputValue(), "9");

    // One card is armed at a time.
    await del.click();
    await other.click();
    assert.equal(await page.locator(".del.armed").count(), 1);
    assert.match(await other.getAttribute("class"), /\barmed\b/);

    // Two taps delete the card, and the header's Undo brings it back.
    await del.click();
    await del.click();
    assert.deepEqual(await names(), before.slice(1));
    await page.locator("#undo").click();
    assert.deepEqual(await names(), before);
  });
});

test("an armed ✕ lets go by itself after 3 seconds, without drawing the cards again",
     async (t) => {
  await onPhone(t, async (page, site) => {
    await openTwoCards(page, site);
    const del = page.locator(".card").first().locator(".del");
    await del.click();
    // The athlete types a load while the ✕ waits; focus moves with no tap on the page.
    const kg = page.locator(".card").first().locator(".num").nth(1);
    await kg.focus();
    await kg.pressSequentially("70");
    assert.match(await del.getAttribute("class"), /\barmed\b/);
    await page.waitForTimeout(3200);
    assert.doesNotMatch(await del.getAttribute("class"), /\barmed\b/);
    assert.equal(await kg.evaluate((field) => field === document.activeElement), true);
    assert.equal(await kg.inputValue(), "70");
    assert.equal(await page.locator(".card").count(), 2);
  });
});

test("the block beside a card's name: ⇆ replaces, 📷 shows the photos, if any", async (t) => {
  await onPhone(t, async (page, site) => {
    await openTwoCards(page, site);
    const bench = page.locator(".card").first();
    const lunge = page.locator(".card").nth(1);
    const columns = (card) => card.locator(".moves")
      .evaluate((block) => getComputedStyle(block).gridTemplateColumns);

    await bench.locator(".replace").click();
    assert.equal(await page.locator("#search-sheet").isVisible(), true);
    assert.equal(await page.locator("#search-title").textContent(), "Replace Bench press");
    await page.locator("#search-close").click();

    // 📷 opens the photos and looks pressed, and a second tap closes them.
    const pic = bench.locator(".pic");
    assert.equal(await pic.getAttribute("aria-pressed"), "false");
    assert.equal(await pic.getAttribute("aria-label"), "Show the photos of Bench press");
    await pic.click();
    assert.equal(await bench.locator(".photos img").count(), 2);
    assert.equal(await pic.getAttribute("aria-pressed"), "true");
    assert.equal(await pic.getAttribute("aria-label"), "Hide the photos of Bench press");
    assert.notEqual(await pic.evaluate((node) => getComputedStyle(node).backgroundColor),
                    "rgba(0, 0, 0, 0)");
    await pic.click();
    assert.equal(await bench.locator(".photos").count(), 0);
    assert.equal(await pic.getAttribute("aria-pressed"), "false");

    // A card whose exercise has no photos has no 📷 and two columns.
    assert.equal(await columns(bench), "36px 36px 36px");
    assert.equal(await lunge.locator(".pic").count(), 0);
    assert.equal(await columns(lunge), "36px 36px");
  });
});
