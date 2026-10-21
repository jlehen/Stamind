// The details page's logic (DESIGN_short_messages.md §6).
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../details_logic.js";

// Proposal #25, the one Tuesday's "🔎 Tell me more" points at.
const FILE = {
  v: 1, at: "2026-10-20T08:03", id: 25,
  summary: "Your recovery is excellent this morning. I restored both lifts this week.",
  cards: [
    { line: "🏋️ Today: Full-Body Strength (Light) — 45 min (moved from Thu Oct 22)",
      why: "Rewritten for its new Tuesday slot.", passages: [], text: "[Gym]\nBench press",
      open: true },
    { line: "🗑 Today: Rest Day — Mobility Yoga — dropped" },
  ],
  notice: "",
};

test("the button's proposal number is read from the address", () => {
  assert.equal(logic.wantedProposal("#p=25&k=abc&b=pages&f=123"), 25);
  assert.equal(logic.wantedProposal("#k=abc&b=pages&f=123"), null);
  assert.equal(logic.wantedProposal("#p=x"), null);
  assert.equal(logic.wantedProposal(""), null);
});

test("the button's own proposal is shown, cards in the order of the file", () => {
  const view = logic.proposalView(FILE, 25);
  assert.equal(view.problem, undefined);
  assert.equal(view.summary, FILE.summary);
  assert.deepEqual(view.cards.map((card) => card.line), FILE.cards.map((card) => card.line));
});

test("an older button meets a newer proposal: it says so and shows nothing else", () => {
  assert.deepEqual(logic.proposalView(FILE, 24), { problem: logic.REPLACED });
});

// October's file, with Tuesday's sheet as the bot wrote it.
const OCTOBER = {
  v: 1, at: "2026-10-20T08:03",
  days: {
    "2026-10-20": { x: ["🏋️"], sheet: [["Planned", ["🏋️ Today: Gym — 45 min", "[Gym]\nBench"]]] },
  },
};

test("the button's day is read from the address, and names its month's file", () => {
  assert.equal(logic.wantedDay("#d=2026-10-20&k=abc&b=pages&f=123"), "2026-10-20");
  assert.equal(logic.wantedDay("#d=yesterday"), null);
  assert.equal(logic.wantedDay("#p=25"), null);
  assert.equal(logic.monthFileLabel("2026-10-20"), "calendar/2026-10");
});

test("a day draws the sheet the Calendar draws", () => {
  const view = logic.dayView(OCTOBER, "2026-10-20");
  assert.deepEqual(view.parts, OCTOBER.days["2026-10-20"].sheet);
  assert.ok(view.title);
});

test("a day with nothing, and a month file that did not arrive", () => {
  assert.deepEqual(logic.dayView(OCTOBER, "2026-10-21"), { problem: logic.NOTHING_PLANNED });
  assert.deepEqual(logic.dayView(null, "2026-10-20"), { problem: logic.COULD_NOT_LOAD });
});

test("a file that did not arrive, or that the upload has not caught up with, asks for a retry",
  () => {
    assert.deepEqual(logic.proposalView(null, 25), { problem: logic.COULD_NOT_LOAD });
    assert.deepEqual(logic.proposalView(FILE, 26), { problem: logic.COULD_NOT_LOAD });
  });
