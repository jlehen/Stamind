// The gym logger's logic, checked against the two payloads in DESIGN_gym_logger.md §3 and §4,
// at version 2: an exercise is named by its key (DESIGN_exercise_table.md §8).
// Run from the repository root: node --test miniapp/tests/
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../logic.js";

// The §3 example, base64url of its UTF-8 JSON, exactly as the bot would put it in the URL.
const EXAMPLE_HASH = "#s=eyJ2IjoyLCJyIjo3MjcsImQiOiIyMDI2LTA5LTI0IiwidCI6Ikd5bTogbG93ZXIgYm9keS"
  + "BzdHJlbmd0aCIsIngi"
  + "Olt7Im4iOiJTUVVBVC9CRUxUX1NRVUFUIiwicyI6MywibG8iOjQsImhpIjo2LCJrZyI6MTQwfSx7Im4iOiJQVUxM"
  + "X1VQL1BVTExfVVAiLCJzIjozLCJsbyI6NiwiaGkiOjgsImtnIjpudWxsfV0sIm5vdGVzIjoiQWx0ZXJuYXRlIHRo"
  + "ZSBzcXVhdCBhbmQgdGhlIHB1bGwtdXBzLiJ9";

// Wednesday 24 September 2026, 18:02 and 19:05 on the phone's own clock.
const START = new Date(2026, 8, 24, 18, 2, 0).getTime();
const END = new Date(2026, 8, 24, 19, 5, 0).getTime();

// Rows as `exercises.json` holds them: the key, the words, the pattern, the gear, bodyweight.
const CATALOG = [
  { k: "SQUAT/BELT_SQUAT", w: "squat: belt squat", p: "squat", g: "Machine", b: false },
  { k: "SQUAT/LEG_PRESS", w: "squat: leg press", p: "squat", g: "Machine", b: false },
  { k: "PULL_UP/PULL_UP", w: "pull up", p: "pull_vertical", g: "Pull-up Bar", b: true },
  { k: "CURL/BARBELL_CURL", w: "curl: barbell curl", p: "accessory", g: "Barbell", b: false },
  { k: "ROW/SEATED_CABLE_ROW", w: "row: seated cable row", p: "pull_horizontal",
    g: "Cable Machine, Cable Attachment", b: false },
  { k: "CARDIO/SQUAT_JACKS", w: "cardio: squat jacks", p: "", g: "Nothing", b: true },
];

function exampleState() {
  return logic.startClock(logic.newState(logic.sessionFromHash(EXAMPLE_HASH)), START);
}

function tickSet(state, xi, si, seconds) {
  return logic.toggleDone(state, xi, si, seconds);
}

test("the session in the URL hash is read as §3 wrote it", () => {
  const session = logic.sessionFromHash(EXAMPLE_HASH);
  assert.equal(session.v, 2);
  assert.equal(session.r, 727);
  assert.equal(session.d, "2026-09-24");
  assert.equal(session.t, "Gym: lower body strength");
  assert.deepEqual(session.x[0], { n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 });
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
  const session = { v: 2, r: 8, d: "2026-09-24", t: "Séance : bas du corps",
                    x: [{ n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 }], notes: "Élan" };
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
  const added = logic.addExercise(state, "CURL/BARBELL_CURL", false);
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
    v: 2,
    r: 727,
    d: "2026-09-24",
    st: "18:02",
    en: "19:05",
    x: [
      { n: "SQUAT/BELT_SQUAT", p: 1, sets: [[5, 120, 40], [6, 140, 210]] },
      { n: "PULL_UP/PULL_UP", p: 2, sets: [[8, null, 300]], note: "strict" },
    ],
    note: "left knee felt off on the squat",
  });
});

test("an exercise with nothing ticked is absent from the log", () => {
  const state = tickSet(exampleState(), 1, 0, 90);
  const log = logic.buildLog(state, END);
  assert.deepEqual(log.x.map((entry) => entry.n), ["PULL_UP/PULL_UP"]);
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
    v: 2, r: 727, d: "2026-09-24", t: "Gym: everything",
    x: Array.from({ length: 12 },
      () => ({ n: "ROW/SEATED_CABLE_ROW", s: 4, lo: 8, hi: 10, kg: 60 })),
  });
  state = logic.startClock(state, START);
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
  state = logic.swapExercise(state, 0, "SQUAT/LEG_PRESS");
  assert.equal(state.x[0].n, "SQUAT/LEG_PRESS");
  assert.equal(state.x[0].p, 1);
  // The written load belonged to the other exercise, so the line drops it and keeps the reps.
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6");
  const entry = logic.buildLog(state, END).x[0];
  assert.deepEqual(entry, { n: "SQUAT/LEG_PRESS", p: 1, sets: [[6, 140, 30]] });
});

test("an added exercise has no position, and has a load unless it is bodyweight", () => {
  let state = exampleState();
  state = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  state = logic.addExercise(state, "PULL_UP/PULL_UP", true);
  assert.equal(state.x[2].p, null);
  assert.equal(state.x[2].sets.length, logic.ADDED_SETS);
  assert.equal(state.x[2].sets[0].kg, logic.ADDED_KG);
  assert.equal(state.x[3].sets[0].kg, null);
  state = tickSet(state, 2, 0, 500);
  const entry = logic.buildLog(state, END).x[0];
  assert.deepEqual(entry, { n: "CURL/BARBELL_CURL", sets: [[8, 20, 500]] });
  assert.equal("p" in entry, false);
});

test("moving an exercise reorders the cards and leaves the positions alone", () => {
  let state = exampleState();
  state = logic.moveExercise(state, 1, -1);
  assert.deepEqual(state.x.map((x) => x.n), ["PULL_UP/PULL_UP", "SQUAT/BELT_SQUAT"]);
  assert.deepEqual(state.x.map((x) => x.p), [2, 1]);
  // Moving past either end changes nothing.
  assert.deepEqual(logic.moveExercise(state, 0, -1), state);
  assert.deepEqual(logic.moveExercise(state, 1, 1), state);
});

test("removing an exercise drops it, removing a set stops at the last one", () => {
  let state = exampleState();
  state = logic.removeExercise(state, 0);
  assert.deepEqual(state.x.map((x) => x.n), ["PULL_UP/PULL_UP"]);
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
  assert.deepEqual(logic.searchExercises(CATALOG, "press", "squat").map((r) => r.k),
                   ["SQUAT/LEG_PRESS"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "press", null).map((r) => r.k),
                   ["SQUAT/LEG_PRESS"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "", "squat").map((r) => r.k),
                   ["SQUAT/LEG_PRESS", "SQUAT/BELT_SQUAT"]);
  // Adding an exercise has no pattern to filter on, so an empty box offers nothing.
  assert.deepEqual(logic.searchExercises(CATALOG, "", null), []);
  assert.deepEqual(logic.searchExercises(CATALOG, "cable row", null).map((r) => r.k),
                   ["ROW/SEATED_CABLE_ROW"]);
});

test("the search reads the words, category included, and gives back the row with its key", () => {
  // "squat" is the category of two exercises and part of the name of a third.
  assert.deepEqual(logic.searchExercises(CATALOG, "squat", null).map((r) => r.k),
                   ["CARDIO/SQUAT_JACKS", "SQUAT/BELT_SQUAT", "SQUAT/LEG_PRESS"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "SQUAT/BELT_SQUAT", null), []);
  assert.equal(logic.wordsOf(CATALOG, "SQUAT/BELT_SQUAT"), "squat: belt squat");
  // A key the catalog lacks shows as it is.
  assert.equal(logic.wordsOf(CATALOG, "SQUAT/MOON_SQUAT"), "SQUAT/MOON_SQUAT");
  assert.equal(logic.patternOf(CATALOG, "PULL_UP/PULL_UP"), "pull_vertical");
  // An exercise with no pattern has none to filter a swap on.
  assert.equal(logic.patternOf(CATALOG, "CARDIO/SQUAT_JACKS"), "");
});

test("the search leaves the word weighted out of what is typed", () => {
  // A weighted twin is its class with a load, so "weighted pull up" finds "pull up".
  assert.deepEqual(logic.searchExercises(CATALOG, "weighted pull up", null).map((r) => r.k),
                   ["PULL_UP/PULL_UP"]);
  assert.deepEqual(logic.searchExercises(CATALOG, "Weighted", null), []);
});

test("the search ranks on the name after the category", async () => {
  // Every entry of the curl category starts with "curl", so ranking on the whole words would
  // fill the forty results with that category and hide the leg curl.
  const { readFile } = await import("node:fs/promises");
  const catalog = JSON.parse(
    await readFile(new URL("../exercises.json", import.meta.url), "utf8"));
  const curls = logic.searchExercises(catalog, "curl", null).map((r) => r.k);
  assert.equal(curls[0], "CURL/CURL");
  assert.ok(curls.indexOf("LEG_CURL/LEG_CURL") >= 0
            && curls.indexOf("LEG_CURL/LEG_CURL") < 10, curls.join(" "));
  assert.equal(logic.searchExercises(catalog, "leg press", null)[0].k, "SQUAT/LEG_PRESS");
  assert.equal(logic.searchExercises(catalog, "weighted pull up", null)[0].k, "PULL_UP/PULL_UP");
});

test("the page draws a session only when it is version 2", () => {
  // A button drawn before the names became keys still carries a version 1 session.
  const old = { v: 1, r: 727, d: "2026-09-24", x: [{ n: "belt squat", s: 3, lo: 4, hi: 6 }] };
  assert.equal(logic.isCurrent(old), false);
  assert.equal(logic.isCurrent(null), false);
  assert.equal(logic.isCurrent(logic.sessionFromHash(EXAMPLE_HASH)), true);
  assert.equal(logic.isCurrent(logic.demoSession()), true);
  // The page was opened from the gym button, so no log rides in its address.
  assert.equal(logic.logFromHash(EXAMPLE_HASH), null);
  assert.equal(logic.outOfDateLine(null),
               "This button is out of date. Send your coach any message and tap the new one.");
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

test("the clock waits for Start, and a second Start does not move it", () => {
  const fresh = logic.newState(logic.sessionFromHash(EXAMPLE_HASH));
  assert.equal(fresh.startedAt, null);
  const started = logic.startClock(fresh, START);
  assert.equal(started.startedAt, START);
  assert.equal(fresh.startedAt, null);
  assert.equal(logic.startClock(started, END).startedAt, START);
});

test("the first Finish stops the clock, and a log sent again ends at the same moment", () => {
  let state = tickSet(exampleState(), 0, 0, 40);
  assert.equal(state.finishedAt, null);
  state = logic.markFinished(state, END);
  const later = END + 20 * 60 * 1000;
  assert.equal(logic.markFinished(state, later).finishedAt, END);
  assert.equal(logic.clockAt(state, later), END);
  // A set ticked after the finish is stamped at the finish, and the log still ends there.
  state = tickSet(state, 0, 1, (logic.clockAt(state, later) - state.startedAt) / 1000);
  const log = logic.buildLog(state, later);
  assert.equal(log.en, "19:05");
  assert.equal(log.d, "2026-09-24");
  assert.deepEqual(log.x[0].sets.map((set) => set[2]), [40, 63 * 60]);
});

test("the header shows the session's own date in words", () => {
  assert.equal(logic.formatDay("2026-09-24"), "Thu Sep 24");
  assert.equal(logic.formatDay(""), "");
  assert.equal(logic.capitalise("squat: belt squat"), "Squat: belt squat");
});

test("the saved state is keyed by its version and the session's revision id", () => {
  // A state saved under the old names has another version, so it is never read.
  assert.equal(logic.storageKey(727), "stamind-gym-v3-r727");
  assert.equal(logic.newState(logic.demoSession()).v, logic.STATE_VERSION);
  assert.notEqual(logic.storageKey(727), logic.storageKey(728));
});

test("an exercise linked to Free Exercise DB has its two photos, any other has none", () => {
  const catalog = [
    { k: "SQUAT/BARBELL_BACK_SQUAT", w: "squat: barbell back squat", p: "squat",
      g: "Barbell, Squat Rack", b: false, f: "Barbell_Squat" },
    { k: "SQUAT/BELT_SQUAT", w: "squat: belt squat", p: "squat", g: "Machine", b: false },
  ];
  assert.deepEqual(logic.photosOf(catalog, "SQUAT/BARBELL_BACK_SQUAT"), [
    `${logic.PHOTO_BASE}Barbell_Squat/0.jpg`,
    `${logic.PHOTO_BASE}Barbell_Squat/1.jpg`,
  ]);
  assert.deepEqual(logic.photosOf(catalog, "SQUAT/BELT_SQUAT"), []);
  assert.deepEqual(logic.photosOf(catalog, "not listed"), []);
});

test("an inserted exercise lands after its card, with an id no other card has", () => {
  let state = exampleState();
  state = logic.addExercise(state, "SQUAT/LEG_PRESS", false, 1);
  assert.deepEqual(state.x.map((x) => x.n),
                   ["SQUAT/BELT_SQUAT", "SQUAT/LEG_PRESS", "PULL_UP/PULL_UP"]);
  assert.equal(state.x[1].p, null);
  state = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  assert.deepEqual(state.x.map((x) => x.id), [1, 3, 2, 4]);
  // "Start over" numbers the written cards after every id the undo history may still hold.
  const over = logic.newState(logic.sessionFromHash(EXAMPLE_HASH), state.nextId);
  assert.deepEqual(over.x.map((x) => x.id), [5, 6]);
});

test("a lighter entry of the same exercise starts as the warm-up, every other card as main", () => {
  // Thursday: "Belt squat 1×5 @ 120, 3×4–6 @ 140", a pull-up, and a leg press on its own.
  const state = logic.newState({ v: 2, r: 1, d: "2026-09-24", x: [
    { n: "SQUAT/BELT_SQUAT", s: 1, lo: 5, hi: 5, kg: 120 },
    { n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 },
    { n: "PULL_UP/PULL_UP", s: 3, lo: 6, hi: 8, kg: null },
    { n: "SQUAT/LEG_PRESS", s: 3, lo: 8, hi: 10, kg: 200 },
  ] });
  assert.deepEqual(state.x.map((x) => x.warmup), [true, false, false, false]);
  const toggled = logic.toggleWarmup(state, 3);
  assert.equal(toggled.x[3].warmup, true);
  // The label stays on the page: the log is the same either way.
  const ticked = logic.toggleDone(logic.startClock(toggled, START), 3, 0, 60);
  assert.deepEqual(logic.buildLog(ticked, END).x,
                   [{ n: "SQUAT/LEG_PRESS", p: 4, sets: [[10, 200, 60]] }]);
});

test("Dup adds the card's exercise right after it, its sets as they stand, none ticked", () => {
  let state = exampleState();
  state = logic.setKg(state, 0, 0, 100);
  state = tickSet(state, 0, 0, 30);
  state = logic.toggleWarmup(state, 0);
  state = logic.duplicateExercise(state, 0);
  assert.deepEqual(state.x.map((x) => x.n),
                   ["SQUAT/BELT_SQUAT", "SQUAT/BELT_SQUAT", "PULL_UP/PULL_UP"]);
  const copy = state.x[1];
  assert.equal(copy.id, 3);
  assert.equal(copy.p, null);
  assert.equal(copy.warmup, true);
  assert.deepEqual(copy.sets.map((set) => [set.reps, set.kg, set.done]),
                   [[6, 100, false], [6, 140, false], [6, 140, false]]);
});

test("a timer reset brings Start back, and the ticked sets are measured from the new start", () => {
  // Start at 17:50 by mistake, a set ticked at 18:05, then the timer reset.
  const early = new Date(2026, 8, 24, 17, 50, 0).getTime();
  let state = logic.startClock(logic.newState(logic.sessionFromHash(EXAMPLE_HASH)), early);
  state = tickSet(state, 0, 0, 15 * 60);
  state = logic.markFinished(state, END);
  state = logic.resetClock(state);
  assert.equal(state.startedAt, null);
  assert.equal(state.finishedAt, null);
  assert.equal(logic.resetClock(state), state);
  // Start again at 18:00: the 18:05 set is five minutes in.
  const restarted = logic.startClock(state, START - 2 * 60 * 1000);
  assert.equal(restarted.x[0].sets[0].t, 5 * 60);
  assert.equal(restarted.clockWas, null);
  // Start again at 18:10 instead: the set came before the start, so it counts as 0.
  assert.equal(logic.startClock(state, START + 8 * 60 * 1000).x[0].sets[0].t, 0);
});

test("Undo takes back the last change anywhere, but never the Finish", () => {
  let state = exampleState();
  let history = [];
  const change = (after, card) => {
    history = logic.record(history, state, card);
    state = after;
  };
  change(tickSet(state, 0, 0, 30), 1);
  change(logic.bumpKg(state, 1, 0, logic.KG_STEP), 2);
  state = logic.markFinished(state, END);
  let result = logic.undoAll(history, state);
  assert.equal(result.state.x[1].sets[0].kg, null);
  assert.equal(result.state.x[0].sets[0].done, true);
  assert.equal(result.state.finishedAt, END);
  result = logic.undoAll(result.history, result.state);
  assert.equal(result.state.x[0].sets[0].done, false);
  assert.equal(logic.undoAll(result.history, result.state), null);
});

test("a card's own undo takes back that card's last change and leaves the others alone", () => {
  let state = exampleState();
  let history = [];
  const change = (after, card) => {
    history = logic.record(history, state, card);
    state = after;
  };
  change(tickSet(state, 0, 0, 30), 1);
  change(logic.bumpKg(state, 1, 0, logic.KG_STEP), 2);
  change(logic.moveExercise(state, 1, -1), null);
  assert.equal(logic.canUndoCard(history, 1), true);
  // The squat is second now; its undo finds it there and unticks the set.
  let result = logic.undoCard(history, state, 1);
  assert.deepEqual(result.state.x.map((x) => x.n), ["PULL_UP/PULL_UP", "SQUAT/BELT_SQUAT"]);
  assert.equal(result.state.x[1].sets[0].done, false);
  assert.equal(result.state.x[0].sets[0].kg, logic.KG_STEP);
  assert.equal(logic.canUndoCard(result.history, 1), false);
  assert.equal(logic.undoCard(result.history, result.state, 1), null);
  // Undoing the move and then the pull-up's weight must not tick the squat's set again.
  result = logic.undoAll(result.history, result.state);
  result = logic.undoAll(result.history, result.state);
  assert.deepEqual(result.state.x.map((x) => x.n), ["SQUAT/BELT_SQUAT", "PULL_UP/PULL_UP"]);
  assert.equal(result.state.x[0].sets[0].done, false);
  assert.equal(result.state.x[1].sets[0].kg, null);
  assert.equal(result.history.length, 0);
});

test("the undo history keeps the last fifty changes", () => {
  const state = exampleState();
  let history = [];
  for (let i = 0; i < logic.UNDO_DEPTH + 5; i += 1) {
    history = logic.record(history, state, null);
  }
  assert.equal(history.length, logic.UNDO_DEPTH);
});

// A past log, opened from the calendar (DESIGN_gym_logger.md §8). The session is the §3 example:
// belt squat 3×4–6 @ 140 and pull up 3×6–8. The log names its exercises by their keys, like the
// session (DESIGN_exercise_table.md §8).
const SENT_LOG = {
  v: 2,
  r: 727,
  d: "2026-09-24",
  st: "18:02",
  en: "19:05",
  x: [
    { n: "CURL/BARBELL_CURL", sets: [[10, 30, 60]] },
    { n: "SQUAT/LEG_PRESS", p: 1, sets: [[5, 120, 200], [6, 140, 400]], note: "rack busy" },
  ],
  note: "left knee felt off",
};

test("an opened log draws its cards in its order: done sets, then written ones not done", () => {
  const state = logic.stateFromLog(logic.sessionFromHash(EXAMPLE_HASH), SENT_LOG);
  assert.deepEqual(state.x.map((x) => x.n),
                   ["CURL/BARBELL_CURL", "SQUAT/LEG_PRESS", "PULL_UP/PULL_UP"]);
  // The cards are drawn in words.
  assert.deepEqual(state.x.map((x) => logic.wordsOf(CATALOG, x.n)),
                   ["curl: barbell curl", "squat: leg press", "pull up"]);
  // The added exercise stands for no written line.
  assert.equal(logic.prescriptionLine(state.x[0]), "added");
  assert.deepEqual(state.x[0].sets, [{ reps: 10, kg: 30, done: true, t: 60 }]);
  // The swap keeps the squat's line without its load, its two done sets and the third unticked.
  assert.equal(logic.prescriptionLine(state.x[1]), "3×4–6");
  assert.equal(state.x[1].note, "rack busy");
  assert.deepEqual(state.x[1].sets.map((set) => [set.reps, set.kg, set.done]),
                   [[5, 120, true], [6, 140, true], [6, 140, false]]);
  // The pull-ups were not done: last, as written, nothing ticked.
  assert.deepEqual(state.x[2].sets.map((set) => set.done), [false, false, false]);
  assert.equal(new Set(state.x.map((x) => x.id)).size, 3);
  assert.equal(logic.doneSetCount(state), 3);
  assert.equal(state.note, "left knee felt off");
});

test("an opened log sent again with no change is the same log, whenever it is sent", () => {
  const state = logic.stateFromLog(logic.sessionFromHash(EXAMPLE_HASH), SENT_LOG);
  const tenDaysLater = new Date(2026, 9, 4, 9, 0, 0).getTime();
  assert.equal(logic.finish(state, tenDaysLater).text, JSON.stringify(SENT_LOG));
  // A set ticked while it is open is stamped at the session's end, on the session's day.
  const more = logic.buildLog(logic.toggleDone(state, 2, 0, 3780), tenDaysLater);
  assert.equal(more.d, "2026-09-24");
  assert.deepEqual(more.x[2], { n: "PULL_UP/PULL_UP", p: 2, sets: [[8, null, 3780]] });
});

test("an opened log shows a key the catalog lacks as it is, and sends every key back", () => {
  // The page's catalog holds the leg press and not the moon squat. The first is drawn in its
  // words and the second as its key. A log sent again names both by their keys.
  const log = { ...SENT_LOG, x: [
    { n: "SQUAT/LEG_PRESS", p: 1, sets: [[5, 120, 200]] },
    { n: "SQUAT/MOON_SQUAT", sets: [[8, 20, 400]] },
  ] };
  const state = logic.stateFromLog(logic.sessionFromHash(EXAMPLE_HASH), log);
  assert.deepEqual(state.x.map((x) => logic.wordsOf(CATALOG, x.n)),
                   ["squat: leg press", "SQUAT/MOON_SQUAT", "pull up"]);
  // The leg press stood for the belt squat: a swap, told by comparing the two keys.
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6");
  const sent = logic.buildLog(state, END);
  assert.equal(sent.v, 2);
  assert.deepEqual(sent.x.map((entry) => entry.n), ["SQUAT/LEG_PRESS", "SQUAT/MOON_SQUAT"]);
});

test("a log stored before the names became keys opens once its names are converted", () => {
  // The conversion rewrites a stored log's names and leaves its version at 1
  // (DESIGN_exercise_table.md §9). The page reads the version of the session beside the log,
  // never the log's own, and the log it sends again is version 2.
  const session = logic.sessionFromHash(EXAMPLE_HASH);
  assert.equal(logic.isCurrent(session), true);
  const state = logic.stateFromLog(session, { ...SENT_LOG, v: 1 });
  assert.deepEqual(state.x.map((x) => x.n),
                   ["CURL/BARBELL_CURL", "SQUAT/LEG_PRESS", "PULL_UP/PULL_UP"]);
  assert.deepEqual(logic.buildLog(state, END), SENT_LOG);
});

test("a past log from a month file built before the names became keys is out of date", () => {
  // Such a file holds the old names and a version 1 session, so the page draws nothing.
  const address = logic.loggedAddress({
    s: { v: 1, r: 727, d: "2026-09-24", x: [{ n: "belt squat", s: 3, lo: 4, hi: 6, kg: 140 }] },
    l: { ...SENT_LOG, v: 1, x: [{ n: "belt squat", p: 1, sets: [[5, 140, 40]] }] },
  });
  const hash = address.slice(address.indexOf("#"));
  assert.equal(logic.isCurrent(logic.sessionFromHash(hash)), false);
  // The athlete tapped a day in the calendar, not a button, so the line says another thing.
  assert.equal(logic.outOfDateLine(logic.logFromHash(hash)),
               "This log is out of date and cannot be opened.");
});

test("an opened log that ran over midnight started the day before", () => {
  const state = logic.stateFromLog(logic.sessionFromHash(EXAMPLE_HASH),
                                   { ...SENT_LOG, st: "23:40", en: "00:25" });
  assert.equal(state.finishedAt - state.startedAt, 45 * 60 * 1000);
  const log = logic.buildLog(state, END);
  assert.deepEqual([log.d, log.st, log.en], ["2026-09-24", "23:40", "00:25"]);
});

test("the calendar's address carries the session and the log, and a gym address no log", () => {
  const session = logic.sessionFromHash(EXAMPLE_HASH);
  const address = logic.loggedAddress({ s: session, l: SENT_LOG });
  assert.match(address, /^\.\/index\.html#s=/);
  const hash = `${address.slice(address.indexOf("#"))}&tgWebAppVersion=8.0`;
  assert.deepEqual(logic.sessionFromHash(hash), session);
  assert.deepEqual(logic.logFromHash(hash), SENT_LOG);
  assert.equal(logic.logFromHash(EXAMPLE_HASH), null);
});
