// The "Export to Markdown" text (DESIGN_gym_logger.md §1).
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../logic.js";
import { toMarkdown } from "../markdown.js";

// Thursday 24 September 2026, 18:02 and 19:05 on the phone's own clock.
const START = new Date(2026, 8, 24, 18, 2, 0).getTime();
const END = new Date(2026, 8, 24, 19, 5, 0).getTime();

// What the page has read from `exercises.json` for these three exercises.
const CATALOG = [
  { k: "SQUAT/BELT_SQUAT", w: "squat: belt squat" },
  { k: "PULL_UP/PULL_UP", w: "pull up" },
  { k: "SQUAT/LEG_EXTENSION", w: "squat: leg extension" },
];

const SESSION = {
  v: 2,
  r: 727,
  d: "2026-09-24",
  t: "Gym: lower body strength",
  x: [
    { n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 },
    { n: "PULL_UP/PULL_UP", s: 3, lo: 6, hi: 8, kg: null },
    { n: "SQUAT/LEG_EXTENSION", s: 2, lo: 12, hi: 15, kg: 45 },
  ],
  notes: "Alternate the squat and the pull-ups.",
};

test("before any set is ticked, the export is the session as the page holds it", () => {
  const state = logic.newState(SESSION);
  assert.equal(toMarkdown(state, START, CATALOG), [
    "### 2026-09-24 [Gym: lower body strength]",
    "",
    "Alternate the squat and the pull-ups.",
    "",
    "- [Squat] Belt squat: 3x6 (140 kg)",
    "- Pull up: 3x8 (bodyweight)",
    "- [Squat] Leg extension: 2x15 (45 kg)",
    "",
  ].join("\n"));
});

test("after a set is ticked, the export holds the ticked sets, notes and the time", () => {
  let state = logic.startClock(logic.newState(SESSION), START);
  state = logic.setReps(state, 0, 0, 5);
  state = logic.setKg(state, 0, 0, 120);
  for (const si of [0, 1, 2]) {
    state = logic.toggleDone(state, 0, si, 60 * si);
  }
  state = logic.toggleDone(state, 1, 0, 300);
  state = logic.setExerciseNote(state, 1, " grip gave out ");
  state = logic.setSessionNote(state, "left knee felt off");
  state = logic.markFinished(state, END);
  assert.equal(toMarkdown(state, END + 600000, CATALOG), [
    "### 2026-09-24 [Gym: lower body strength]",
    "18:02–19:05 (63 min)",
    "",
    "Alternate the squat and the pull-ups.",
    "",
    "- [Squat] Belt squat: 1x5 (120 kg), 2x6 (140 kg)",
    "- Pull up: 1x8 (bodyweight) — grip gave out",
    "",
    "Note: left knee felt off",
    "",
  ].join("\n"));
});

test("a card marked as a warm-up says so in the export", () => {
  const state = logic.toggleWarmup(logic.newState(SESSION), 2);
  assert.match(toMarkdown(state, START, CATALOG),
               /^- \[Squat\] Leg extension \(warm-up\): 2x15 \(45 kg\)$/m);
});
