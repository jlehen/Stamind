// The gym logger's logic, checked against the two payloads in DESIGN_gym_logger.md §3 and §4.
// Run from the repository root: node --test miniapp/tests/
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../logic.js";

// The §3 example, base64url of its UTF-8 JSON, exactly as the bot would put it in the URL.
const EXAMPLE_HASH = "#s=eyJ2IjoxLCJyIjo3MjcsImQiOiIyMDI2LTA5LTI0IiwidCI6Ikd5bTogbG93ZXIgYm9keS"
  + "BzdHJlbmd0aCIsIngiOlt7Im4iOiJiZWx0IHNxdWF0IiwicyI6MywibG8iOjQsImhpIjo2LCJrZyI6MTQwfSx7Im4i"
  + "OiJwdWxsIHVwIiwicyI6MywibG8iOjYsImhpIjo4LCJrZyI6bnVsbH1dLCJub3RlcyI6IkFsdGVybmF0ZSB0aGUgc3"
  + "F1YXQgYW5kIHRoZSBwdWxsLXVwcy4ifQ";

// Wednesday 24 September 2026, 18:02 and 19:05 on the phone's own clock.
const START = new Date(2026, 8, 24, 18, 2, 0).getTime();
const END = new Date(2026, 8, 24, 19, 5, 0).getTime();

const CATALOG = [
  { n: "belt squat", p: "squat", e: "machine" },
  { n: "leg press", p: "squat", e: "machine" },
  { n: "pull up", p: "pull_vertical", e: "bodyweight" },
  { n: "barbell curl", p: "accessory", e: "barbell" },
  { n: "seated cable row", p: "pull_horizontal", e: "cable" },
];

function exampleState() {
  return logic.newState(logic.sessionFromHash(EXAMPLE_HASH), START);
}

function tickSet(state, xi, si, seconds) {
  return logic.toggleDone(state, xi, si, seconds);
}

test("the session in the URL hash is read as §3 wrote it", () => {
  const session = logic.sessionFromHash(EXAMPLE_HASH);
  assert.equal(session.v, 1);
  assert.equal(session.r, 727);
  assert.equal(session.d, "2026-09-24");
  assert.equal(session.t, "Gym: lower body strength");
  assert.deepEqual(session.x[0], { n: "belt squat", s: 3, lo: 4, hi: 6, kg: 140 });
  assert.equal(session.x[1].kg, null);
  assert.equal(session.notes, "Alternate the squat and the pull-ups.");
});

test("a URL with no session in it reads as nothing", () => {
  assert.equal(logic.sessionFromHash(""), null);
  assert.equal(logic.sessionFromHash("#other=1"), null);
});

test("encoding a session and reading it back gives the same session", () => {
  const session = logic.demoSession();
  const round = logic.decodeSession(logic.encodeSession(session));
  assert.deepEqual(round, session);
  assert.match(logic.encodeSession(session), /^[A-Za-z0-9_-]+$/);
});

test("a session with accents survives the trip", () => {
  const session = { v: 1, r: 8, d: "2026-09-24", t: "Séance : bas du corps",
                    x: [{ n: "belt squat", s: 3, lo: 4, hi: 6, kg: 140 }], notes: "Élan" };
  assert.deepEqual(logic.decodeSession(logic.encodeSession(session)), session);
});

test("a new state prefills every set with the top of the rep range and the written load", () => {
  const state = exampleState();
  assert.equal(state.x.length, 2);
  assert.deepEqual(state.x[0].sets, [
    { reps: 6, kg: 140, done: false, t: null },
    { reps: 6, kg: 140, done: false, t: null },
    { reps: 6, kg: 140, done: false, t: null },
  ]);
  assert.equal(state.x[1].sets[0].kg, null);
  assert.deepEqual([state.x[0].p, state.x[1].p], [1, 2]);
});

test("the prescription line reads the way the coach wrote it", () => {
  const state = exampleState();
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6 @ 140 kg");
  assert.equal(logic.prescriptionLine(state.x[1]), "3×6–8");
  const added = logic.addExercise(state, "barbell curl", "barbell");
  assert.equal(logic.prescriptionLine(added.x[2]), "added");
});

test("the log holds the done sets only, and the day comes from the phone's clock", () => {
  let state = exampleState();
  state = tickSet(state, 0, 0, 40);
  state = logic.setReps(state, 0, 0, 5);
  state = logic.setKg(state, 0, 0, 120);
  state = tickSet(state, 0, 1, 210);
  state = tickSet(state, 1, 0, 300);
  state = logic.setExerciseNote(state, 1, "  strict  ");
  state = logic.setSessionNote(state, "left knee felt off on the squat");
  const log = logic.buildLog(state, END);
  assert.deepEqual(log, {
    v: 1,
    r: 727,
    d: "2026-09-24",
    st: "18:02",
    en: "19:05",
    x: [
      { n: "belt squat", p: 1, sets: [[5, 120, 40], [6, 140, 210]] },
      { n: "pull up", p: 2, sets: [[8, null, 300]], note: "strict" },
    ],
    note: "left knee felt off on the squat",
  });
});

test("an exercise with nothing ticked is absent from the log", () => {
  const state = tickSet(exampleState(), 1, 0, 90);
  const log = logic.buildLog(state, END);
  assert.deepEqual(log.x.map((entry) => entry.n), ["pull up"]);
});

test("the log's day is the day the athlete lifted, not the session's date", () => {
  // The session is written for Thursday 24; the athlete trains on Wednesday 23 instead.
  const wednesday = new Date(2026, 8, 23, 19, 30, 0).getTime();
  const state = tickSet(exampleState(), 0, 0, 30);
  const log = logic.buildLog(state, wednesday);
  assert.equal(log.d, "2026-09-23");
  assert.equal(log.r, 727);
});

test("a log over 4,096 bytes is refused, a normal one is not", () => {
  let state = exampleState();
  state = tickSet(state, 0, 0, 30);
  const normal = logic.finish(state, END);
  assert.equal(normal.fits, true);
  assert.ok(normal.bytes < 200);

  state = logic.setSessionNote(state, "x".repeat(logic.MAX_LOG_BYTES));
  const heavy = logic.finish(state, END);
  assert.equal(heavy.fits, false);
  assert.ok(heavy.bytes > logic.MAX_LOG_BYTES);
});

test("a full twelve-exercise session still fits in one message", () => {
  // §4: forty-two sets of twelve exercises take about 1 KB.
  let state = logic.newState({
    v: 1, r: 727, d: "2026-09-24", t: "Gym: everything",
    x: Array.from({ length: 12 }, () => ({ n: "seated cable row", s: 4, lo: 8, hi: 10, kg: 60 })),
  }, START);
  for (let xi = 0; xi < 12; xi += 1) {
    for (let si = 0; si < 4; si += 1) {
      state = tickSet(state, xi, si, 60 * (xi * 4 + si));
    }
  }
  const result = logic.finish(state, END);
  assert.equal(result.fits, true);
  assert.ok(result.bytes < 1600, `a full session is ${result.bytes} bytes`);
});

test("a swapped exercise keeps the position of the row it replaced", () => {
  let state = exampleState();
  state = tickSet(state, 0, 0, 30);
  state = logic.swapExercise(state, 0, "leg press");
  assert.equal(state.x[0].n, "leg press");
  assert.equal(state.x[0].p, 1);
  // The written load belonged to the other exercise, so the line drops it and keeps the reps.
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6");
  const entry = logic.buildLog(state, END).x[0];
  assert.deepEqual(entry, { n: "leg press", p: 1, sets: [[6, 140, 30]] });
});

test("an added exercise has no position, and takes its load from its equipment", () => {
  let state = exampleState();
  state = logic.addExercise(state, "barbell curl", "barbell");
  state = logic.addExercise(state, "pull up", "bodyweight");
  assert.equal(state.x[2].p, null);
  assert.equal(state.x[2].sets.length, logic.ADDED_SETS);
  assert.equal(state.x[2].sets[0].kg, logic.ADDED_KG);
  assert.equal(state.x[3].sets[0].kg, null);
  state = tickSet(state, 2, 0, 500);
  const entry = logic.buildLog(state, END).x[0];
  assert.deepEqual(entry, { n: "barbell curl", sets: [[8, 20, 500]] });
  assert.equal("p" in entry, false);
});

test("moving an exercise reorders the cards and leaves the positions alone", () => {
  let state = exampleState();
  state = logic.moveExercise(state, 1, -1);
  assert.deepEqual(state.x.map((x) => x.n), ["pull up", "belt squat"]);
  assert.deepEqual(state.x.map((x) => x.p), [2, 1]);
  // Moving past either end changes nothing.
  assert.deepEqual(logic.moveExercise(state, 0, -1), state);
  assert.deepEqual(logic.moveExercise(state, 1, 1), state);
});

test("removing an exercise drops it, removing a set stops at the last one", () => {
  let state = exampleState();
  state = logic.removeExercise(state, 0);
  assert.deepEqual(state.x.map((x) => x.n), ["pull up"]);
  state = logic.removeSet(state, 0);
  state = logic.removeSet(state, 0);
  assert.equal(state.x[0].sets.length, 1);
  state = logic.removeSet(state, 0);
  assert.equal(state.x[0].sets.length, 1);
});

test("adding a set copies the last one and leaves it unticked", () => {
  let state = exampleState();
  state = logic.setKg(state, 0, 2, 145);
  state = tickSet(state, 0, 2, 300);
  state = logic.addSet(state, 0);
  assert.deepEqual(state.x[0].sets[3], { reps: 6, kg: 145, done: false, t: null });
});

test("the kilogram stepper walks down to zero and one tap further to bodyweight", () => {
  let state = exampleState();
  state = logic.setKg(state, 0, 0, 5);
  state = logic.bumpKg(state, 0, 0, -logic.KG_STEP);
  assert.equal(state.x[0].sets[0].kg, 2.5);
  state = logic.bumpKg(state, 0, 0, -logic.KG_STEP);
  assert.equal(state.x[0].sets[0].kg, 0);
  state = logic.bumpKg(state, 0, 0, -logic.KG_STEP);
  assert.equal(state.x[0].sets[0].kg, null);
  state = logic.bumpKg(state, 0, 0, logic.KG_STEP);
  assert.equal(state.x[0].sets[0].kg, 2.5);
  assert.equal(logic.formatKg(null), "BW");
});

test("reps never go below one", () => {
  let state = exampleState();
  state = logic.setReps(state, 0, 0, 1);
  state = logic.bumpReps(state, 0, 0, -1);
  assert.equal(state.x[0].sets[0].reps, 1);
});

test("unticking a set takes it out of the log again", () => {
  let state = tickSet(exampleState(), 0, 0, 30);
  state = tickSet(state, 0, 0, 90);
  assert.equal(state.x[0].sets[0].done, false);
  assert.equal(state.x[0].sets[0].t, null);
  assert.deepEqual(logic.buildLog(state, END).x, []);
});

test("the search filters by movement pattern until the athlete asks for everything", () => {
  assert.deepEqual(logic.searchExercises(CATALOG, "press", "squat").map((r) => r.n),
                   ["leg press"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "press", null).map((r) => r.n), ["leg press"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "", "squat").map((r) => r.n),
                   ["leg press", "belt squat"]);
  // Adding an exercise has no pattern to filter on, so an empty box offers nothing.
  assert.deepEqual(logic.searchExercises(CATALOG, "", null), []);
  assert.deepEqual(logic.searchExercises(CATALOG, "cable row", null).map((r) => r.n),
                   ["seated cable row"]);
});

test("the rest timer counts from the last ticked set", () => {
  let state = exampleState();
  assert.equal(logic.lastSetSeconds(state), 0);
  state = tickSet(state, 0, 0, 40);
  state = tickSet(state, 0, 1, 210);
  assert.equal(logic.lastSetSeconds(state), 210);
  assert.equal(logic.doneSetCount(state), 2);
  assert.equal(logic.formatMMSS(75), "01:15");
  assert.equal(logic.formatMMSS(-3), "00:00");
});

test("the header shows the session's own date in words", () => {
  assert.equal(logic.formatDay("2026-09-24"), "Thu Sep 24");
  assert.equal(logic.formatDay(""), "");
  assert.equal(logic.capitalise("belt squat"), "Belt squat");
});

test("the saved state is keyed by the session's revision id", () => {
  assert.equal(logic.storageKey(727), "stamind-gym-v1-r727");
  assert.notEqual(logic.storageKey(727), logic.storageKey(728));
});
