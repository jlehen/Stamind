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

// The positions of the written lines each card stands for.
function positions(state) {
  return state.x.map((x) => x.lines.map((line) => line.p));
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
    { reps: 6, kg: 140, done: false, t: null, p: 1, w: false },
    { reps: 6, kg: 140, done: false, t: null, p: 1, w: false },
    { reps: 6, kg: 140, done: false, t: null, p: 1, w: false },
  ]);
  assert.equal(state.x[1].sets[0].kg, null);
  assert.deepEqual(positions(state), [[1], [2]]);
  assert.deepEqual(state.x[0].lines, [{ p: 1, s: 3, lo: 4, hi: 6, kg: 140 }]);
});

test("the prescription line reads the way the coach wrote it", () => {
  const state = exampleState();
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6 @ 140 kg");
  assert.equal(logic.prescriptionLine(state.x[1]), "3×6–8");
  const added = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  assert.equal(logic.prescriptionLine(added.x[2]), "added");
});

test("an exercise done one side at a time says so after its reps", () => {
  // `o` is the catalog's mark for it: the reps are per side and a set is both sides.
  const catalog = [...CATALOG, { k: "ROW/ONE_ARM_BENT_OVER_ROW", o: true }];
  assert.equal(logic.perSideOf(catalog, "ROW/ONE_ARM_BENT_OVER_ROW"), true);
  assert.equal(logic.perSideOf(catalog, "SQUAT/BELT_SQUAT"), false);
  assert.equal(logic.perSideOf(catalog, "SQUAT/MOON_SQUAT"), false);
  const card = { lines: [{ p: 1, s: 3, lo: 8, hi: 10, kg: 30 }] };
  assert.equal(logic.prescriptionLine(card, true), "3×8–10/side @ 30 kg");
  assert.equal(logic.prescriptionLine(card, false), "3×8–10 @ 30 kg");
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
    // Two exercises in turn, so the twelve rows stay twelve cards.
    x: Array.from({ length: 12 }, (_, i) => (
      { n: i % 2 ? "ROW/SEATED_CABLE_ROW" : "SQUAT/LEG_PRESS", s: 4, lo: 8, hi: 10, kg: 60 })),
  });
  assert.equal(state.x.length, 12);
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
  assert.deepEqual(positions(state), [[1], [2]]);
  assert.deepEqual(state.x[0].sets.map((set) => set.p), [1, 1, 1]);
  // The written load belonged to the other exercise, so the line drops it and keeps the reps.
  assert.equal(logic.prescriptionLine(state.x[0]), "3×4–6");
  const entry = logic.buildLog(state, END).x[0];
  assert.deepEqual(entry, { n: "SQUAT/LEG_PRESS", p: 1, sets: [[6, 140, 30]] });
});

test("an added exercise has no position, and has a load unless it is bodyweight", () => {
  let state = exampleState();
  state = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  state = logic.addExercise(state, "PULL_UP/PULL_UP", true);
  assert.deepEqual(state.x[2].lines, []);
  assert.deepEqual(state.x[2].sets.map((set) => [set.p, set.w]),
                   Array(logic.ADDED_SETS).fill([null, false]));
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
  assert.deepEqual(positions(state), [[2], [1]]);
  // Moving past either end changes nothing.
  assert.deepEqual(logic.moveExercise(state, 0, -1), state);
  assert.deepEqual(logic.moveExercise(state, 1, 1), state);
});

test("swapping two exercises makes them trade places and leaves the positions alone", () => {
  let state = exampleState();
  state = logic.addExercise(state, "ROW/SEATED_CABLE_ROW", false);
  state = logic.swapExercises(state, 0, 2);
  assert.deepEqual(state.x.map((x) => x.n),
                   ["ROW/SEATED_CABLE_ROW", "PULL_UP/PULL_UP", "SQUAT/BELT_SQUAT"]);
  assert.deepEqual(positions(state), [[], [2], [1]]);
  // A card with itself, or a place that is not there, changes nothing.
  assert.deepEqual(logic.swapExercises(state, 1, 1), state);
  assert.deepEqual(logic.swapExercises(state, 0, 3), state);
});

test("moving an exercise above another puts it right there, or at the end", () => {
  let state = exampleState();
  state = logic.addExercise(state, "ROW/SEATED_CABLE_ROW", false);
  const names = (s) => s.x.map((x) => x.n.split("/")[1]);
  assert.deepEqual(names(state), ["BELT_SQUAT", "PULL_UP", "SEATED_CABLE_ROW"]);
  // Up: the row goes above the squat. Down: the squat goes above the row's old neighbour.
  assert.deepEqual(names(logic.moveExerciseAbove(state, 2, 0)),
                   ["SEATED_CABLE_ROW", "BELT_SQUAT", "PULL_UP"]);
  assert.deepEqual(names(logic.moveExerciseAbove(state, 0, 2)),
                   ["PULL_UP", "BELT_SQUAT", "SEATED_CABLE_ROW"]);
  // The number of cards as the place means the end.
  assert.deepEqual(names(logic.moveExerciseAbove(state, 0, 3)),
                   ["PULL_UP", "SEATED_CABLE_ROW", "BELT_SQUAT"]);
  // Above itself, above the card it already sits above, or a place that is not there.
  assert.deepEqual(logic.moveExerciseAbove(state, 1, 1), state);
  assert.deepEqual(logic.moveExerciseAbove(state, 1, 2), state);
  assert.deepEqual(logic.moveExerciseAbove(state, 2, 3), state);
  assert.deepEqual(logic.moveExerciseAbove(state, 0, 4), state);
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
  assert.deepEqual(state.x[0].sets[3], { reps: 6, kg: 145, done: false, t: null, p: 1, w: false });
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
  assert.equal(logic.wordsOf(CATALOG, "SQUAT/BELT_SQUAT"), "[Squat] Belt squat");
  // A key the catalog lacks shows as it is.
  assert.equal(logic.wordsOf(CATALOG, "SQUAT/MOON_SQUAT"), "SQUAT/MOON_SQUAT");
  assert.equal(logic.patternOf(CATALOG, "PULL_UP/PULL_UP"), "pull_vertical");
  // An exercise with no pattern has none to filter a Replace on.
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
  // Garmin writes "one arm" and "single arm" for the same thing (DESIGN_exercise_table.md §7).
  assert.deepEqual(logic.searchExercises(catalog, "single arm cable lateral", null)
    .map((r) => r.k), ["LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE"]);
  assert.equal(curls[0], "CURL/CURL");
  assert.ok(curls.indexOf("LEG_CURL/LEG_CURL") >= 0
            && curls.indexOf("LEG_CURL/LEG_CURL") < 10, curls.join(" "));
  assert.equal(logic.searchExercises(catalog, "leg press", null)[0].k, "SQUAT/LEG_PRESS");
  assert.equal(logic.searchExercises(catalog, "weighted pull up", null)[0].k, "PULL_UP/PULL_UP");
});

test("the search finds a class by the name people use for it", async () => {
  // Garmin's "cable core press" is what people call the Pallof press.
  const { readFile } = await import("node:fs/promises");
  const catalog = JSON.parse(
    await readFile(new URL("../exercises.json", import.meta.url), "utf8"));
  assert.deepEqual(logic.searchExercises(catalog, "pallof", null).map((r) => r.k),
                   ["CORE/CABLE_CORE_PRESS"]);
  assert.deepEqual(logic.searchExercises(catalog, "Pallof press", null).map((r) => r.k),
                   ["CORE/CABLE_CORE_PRESS"]);
  assert.equal(logic.searchExercises(catalog, "copenhagen", null)[0].k, "PLANK/COPENHAGEN_PLANK");
  // The name people use ranks like the name, ahead of "banded exercises: back extension".
  assert.equal(logic.searchExercises(catalog, "back extension", null)[0].k,
               "HYPEREXTENSION/HYPEREXTENSION");
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
  assert.equal(logic.shown("squat: belt squat"), "[Squat] Belt squat");
  assert.equal(logic.shown("pull up"), "Pull up");
});

test("the saved state is keyed by its version and the session's date", () => {
  // A state saved under the old names has another version, so it is never read.
  assert.equal(logic.storageKey("2026-11-16"), "stamind-gym-v4-d2026-11-16");
  assert.equal(logic.newState(logic.demoSession()).v, logic.STATE_VERSION);
});

test("a day's saved state wins over a newer revision once the athlete has started it", () => {
  // It is Monday. The athlete logs revision 1019, the coach has since written 1022, and the
  // button rebuilt after the send carries 1022.
  const old = { ...logic.demoSession(), r: 1019 };
  const rewritten = { ...logic.demoSession(), r: 1022 };
  const untouched = logic.newState(old);
  assert.equal(logic.keepsSaved(untouched, old), true);
  assert.equal(logic.keepsSaved(untouched, rewritten), false);
  assert.equal(logic.keepsSaved(logic.toggleDone(untouched, 0, 0, 30), rewritten), true);
  assert.equal(logic.keepsSaved(logic.startClock(untouched, Date.now()), rewritten), true);
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
  assert.deepEqual(state.x[1].lines, []);
  state = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  assert.deepEqual(state.x.map((x) => x.id), [1, 3, 2, 4]);
  // "Start over" numbers the written cards after every id the undo history may still hold.
  const over = logic.newState(logic.sessionFromHash(EXAMPLE_HASH), state.nextId);
  assert.deepEqual(over.x.map((x) => x.id), [5, 6]);
});

// Thursday: "Belt squat 1×5 @ 120, 3×4–6 @ 140", a pull-up, and a leg press on its own.
const THURSDAY = { v: 2, r: 1, d: "2026-09-24", t: "Gym", x: [
  { n: "SQUAT/BELT_SQUAT", s: 1, lo: 5, hi: 5, kg: 120 },
  { n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 },
  { n: "PULL_UP/PULL_UP", s: 3, lo: 6, hi: 8, kg: null },
  { n: "SQUAT/LEG_PRESS", s: 3, lo: 8, hi: 10, kg: 200 },
] };

test("rows next to each other with the same exercise are one card, its lines in order", () => {
  const state = logic.newState(THURSDAY);
  assert.deepEqual(state.x.map((x) => x.n),
                   ["SQUAT/BELT_SQUAT", "PULL_UP/PULL_UP", "SQUAT/LEG_PRESS"]);
  assert.deepEqual(positions(state), [[1, 2], [3], [4]]);
  assert.deepEqual(state.x[0].sets.map((set) => [set.reps, set.kg, set.p]),
                   [[5, 120, 1], [6, 140, 2], [6, 140, 2], [6, 140, 2]]);
  assert.equal(logic.prescriptionLine(state.x[0]), "1×5 @ 120 kg, 3×4–6 @ 140 kg");
  assert.deepEqual(state.x.map((x) => x.id), [1, 2, 3]);
  assert.equal(state.nextId, 4);
  // The same exercise with another one between stays two cards; a chain merges the same way.
  const chain = "HIP_RAISE/KETTLEBELL_SWING>SQUAT/GOBLET_SQUAT";
  const apart = logic.newState({ ...THURSDAY, x: [
    ...THURSDAY.x,
    { n: "SQUAT/BELT_SQUAT", s: 2, lo: 8, hi: 8, kg: 100 },
    { n: chain, s: 1, lo: 5, hi: 5, kg: 8 },
    { n: chain, s: 3, lo: 5, hi: 8, kg: 12 },
  ] });
  assert.deepEqual(apart.x.map((x) => x.n), ["SQUAT/BELT_SQUAT", "PULL_UP/PULL_UP",
    "SQUAT/LEG_PRESS", "SQUAT/BELT_SQUAT", chain]);
  assert.deepEqual(positions(apart), [[1, 2], [3], [4], [5], [6, 7]]);
});

test("a lighter line of the same exercise opens as warm-up sets, every other set as main", () => {
  const state = logic.newState(THURSDAY);
  assert.deepEqual(state.x.map((x) => x.sets.map((set) => set.w)),
                   [[true, false, false, false], [false, false, false], [false, false, false]]);
  // A tap switches one row and leaves the card's other rows alone.
  const toggled = logic.toggleWarmup(state, 2, 0);
  assert.deepEqual(toggled.x[2].sets.map((set) => set.w), [true, false, false]);
  assert.deepEqual(logic.toggleWarmup(toggled, 2, 0), state);
  // The mark stays on the page: the log is the same either way.
  const ticked = logic.toggleDone(logic.startClock(toggled, START), 2, 0, 60);
  assert.deepEqual(logic.buildLog(ticked, END).x,
                   [{ n: "SQUAT/LEG_PRESS", p: 4, sets: [[10, 200, 60]] }]);
});

test("a warm-up row goes after the last warm-up row, or on top when there is none", () => {
  let state = logic.newState(THURSDAY);
  state = logic.setKg(state, 0, 0, 110);
  state = tickSet(logic.startClock(state, START), 0, 0, 30);
  // The belt squat has a warm-up row: the new one copies it, unticked, under its line.
  state = logic.addWarmup(state, 0);
  assert.deepEqual(state.x[0].sets.slice(0, 3).map((set) => [set.reps, set.kg, set.p, set.w,
                                                             set.done]),
                   [[5, 110, 1, true, true], [5, 110, 1, true, false], [6, 140, 2, false, false]]);
  // The leg press has none: the new row goes on top, a copy of the first set the athlete
  // lowers, and it stands for no line.
  state = logic.setReps(state, 2, 0, 9);
  state = logic.addWarmup(state, 2);
  assert.deepEqual(state.x[2].sets.map((set) => [set.reps, set.kg, set.p, set.w]),
                   [[9, 200, null, true], [9, 200, 4, false], [10, 200, 4, false],
                    [10, 200, 4, false]]);
});

test("the Set pill adds and removes main rows, the W Set pill warm-up rows", () => {
  let state = logic.newState(THURSDAY);
  // The belt squat's last row is made a warm-up: a new main row copies the last main row.
  state = logic.setKg(logic.toggleWarmup(state, 0, 3), 0, 2, 145);
  state = logic.addSet(state, 0);
  assert.deepEqual(state.x[0].sets.map((set) => [set.kg, set.p, set.w]),
                   [[120, 1, true], [140, 2, false], [145, 2, false], [140, 2, true],
                    [145, 2, false]]);
  // The Set pill's "−" takes the last main row, the W Set pill's the last warm-up row.
  state = logic.removeSet(logic.removeSet(state, 0), 0);
  state = logic.removeWarmup(state, 0);
  assert.deepEqual(state.x[0].sets.map((set) => [set.kg, set.w]), [[120, true], [140, false]]);
  // A card with no main row: a new main row copies its last row.
  state = logic.removeSet(state, 0);
  assert.deepEqual(state.x[0].sets.map((set) => set.w), [true]);
  // Neither "−" takes the last set, and the W Set pill's does nothing with no warm-up row.
  assert.equal(logic.removeWarmup(state, 0), state);
  assert.equal(logic.removeSet(state, 0), state);
  assert.equal(logic.removeWarmup(state, 1), state);
  state = logic.addSet(state, 0);
  assert.deepEqual(state.x[0].sets[1], { reps: 5, kg: 120, done: false, t: null, p: 1, w: false });
});

test("a card's done sets go out as one entry per line, the note on the card's last one", () => {
  let state = logic.startClock(logic.newState(THURSDAY), START);
  // The athlete makes the 120 kg line a main set, adds a warm-up of their own on top, then
  // marks the 120 kg line a warm-up again.
  state = logic.toggleWarmup(state, 0, 0);
  state = logic.addWarmup(state, 0);
  state = logic.setKg(state, 0, 0, 60);
  state = logic.toggleWarmup(state, 0, 1);
  assert.deepEqual(state.x[0].sets.map((set) => [set.kg, set.p, set.w]),
                   [[60, null, true], [120, 1, true], [140, 2, false], [140, 2, false],
                    [140, 2, false]]);
  for (const [si, seconds] of [[0, 10], [1, 100], [2, 200], [3, 300]]) {
    state = tickSet(state, 0, si, seconds);
  }
  state = logic.setExerciseNote(state, 0, "deep");
  state = tickSet(state, 1, 0, 400);
  assert.deepEqual(logic.buildLog(state, END).x, [
    { n: "SQUAT/BELT_SQUAT", sets: [[5, 60, 10]] },
    { n: "SQUAT/BELT_SQUAT", p: 1, sets: [[5, 120, 100]] },
    { n: "SQUAT/BELT_SQUAT", p: 2, sets: [[6, 140, 200], [6, 140, 300]], note: "deep" },
    { n: "PULL_UP/PULL_UP", p: 3, sets: [[8, null, 400]] },
  ]);
});

test("Replace on a card of two lines renames every row and drops both written loads", () => {
  let state = tickSet(logic.startClock(logic.newState(THURSDAY), START), 0, 0, 30);
  state = logic.swapExercise(state, 0, "SQUAT/LEG_PRESS");
  assert.equal(state.x[0].n, "SQUAT/LEG_PRESS");
  assert.equal(logic.prescriptionLine(state.x[0]), "1×5, 3×4–6");
  assert.deepEqual(state.x[0].sets.map((set) => [set.kg, set.p, set.w]),
                   [[120, 1, true], [140, 2, false], [140, 2, false], [140, 2, false]]);
  assert.deepEqual(logic.buildLog(state, END).x,
                   [{ n: "SQUAT/LEG_PRESS", p: 1, sets: [[5, 120, 30]] }]);
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

test("a resume after Finish runs the clock on from the same start", () => {
  let state = tickSet(exampleState(), 0, 0, 30);
  const started = state.startedAt;
  state = logic.markFinished(state, END);
  assert.equal(logic.clockAt(state, END + 60_000), END);
  state = logic.resumeClock(state);
  assert.equal(state.finishedAt, null);
  assert.equal(state.startedAt, started);
  assert.equal(state.x[0].sets[0].done, true);
  assert.equal(logic.clockAt(state, END + 60_000), END + 60_000);
  assert.equal(logic.resumeClock(state), state);
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
                   ["[Curl] Barbell curl", "[Squat] Leg press", "Pull up"]);
  // The added exercise stands for no written line.
  assert.equal(logic.prescriptionLine(state.x[0]), "added");
  assert.deepEqual(state.x[0].sets, [{ reps: 10, kg: 30, done: true, t: 60, p: null, w: false }]);
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
                   ["[Squat] Leg press", "SQUAT/MOON_SQUAT", "Pull up"]);
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

test("an opened log the new page sent gives back the cards the athlete sent it from", () => {
  let state = logic.startClock(logic.newState(THURSDAY), START);
  // An added card's sets left unticked are not in the log, so this one keeps one set.
  state = logic.addExercise(state, "CURL/BARBELL_CURL", false);
  state = logic.removeSet(logic.removeSet(state, 3), 3);
  for (const [xi, si, seconds] of [[0, 0, 30], [0, 1, 200], [0, 2, 400], [1, 0, 600],
                                   [2, 0, 800], [3, 0, 900]]) {
    state = tickSet(state, xi, si, seconds);
  }
  state = logic.setExerciseNote(state, 0, "deep");
  state = logic.markFinished(state, END);
  const log = logic.buildLog(state, END);
  const opened = logic.stateFromLog(THURSDAY, log);
  assert.deepEqual(opened.x, state.x);
  assert.equal(logic.finish(opened, END).text, logic.logText(log));
});

test("an opened log from the old page, its warm-up cards apart, opens and sends the same", () => {
  // The old page drew one card per row. The athlete did the belt squat warm-up, then the
  // pull-ups, then the main belt squat sets; and a lighter leg press of their own before the
  // written one.
  const old = { v: 2, r: 1, d: "2026-09-24", st: "18:02", en: "19:05", x: [
    { n: "SQUAT/BELT_SQUAT", p: 1, sets: [[5, 120, 60]], note: "easy" },
    { n: "PULL_UP/PULL_UP", p: 3, sets: [[8, null, 200]] },
    { n: "SQUAT/BELT_SQUAT", p: 2, sets: [[6, 140, 400]] },
    { n: "SQUAT/LEG_PRESS", sets: [[10, 150, 600]], note: "light" },
    { n: "SQUAT/LEG_PRESS", p: 4, sets: [[10, 200, 800]], note: "seat 5" },
  ] };
  const state = logic.stateFromLog(THURSDAY, old);
  assert.deepEqual(state.x.map((x) => x.n), ["SQUAT/BELT_SQUAT", "PULL_UP/PULL_UP",
    "SQUAT/BELT_SQUAT", "SQUAT/LEG_PRESS"]);
  assert.deepEqual(positions(state), [[1], [3], [2], [4]]);
  // The lighter leg press stood for no line, and is a warm-up by its load.
  assert.deepEqual(state.x[3].sets.map((set) => [set.kg, set.p, set.w, set.done]),
                   [[150, null, true, true], [200, 4, false, true], [200, 4, false, false],
                    [200, 4, false, false]]);
  assert.equal(state.x[3].note, "light; seat 5");
  assert.deepEqual(state.x[0].sets.map((set) => set.w), [true]);
  const sent = logic.buildLog(state, END).x;
  assert.deepEqual(sent.slice(0, 3), old.x.slice(0, 3));
  assert.deepEqual(sent.slice(3), [
    { n: "SQUAT/LEG_PRESS", sets: [[10, 150, 600]] },
    { n: "SQUAT/LEG_PRESS", p: 4, sets: [[10, 200, 800]], note: "light; seat 5" },
  ]);
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

// The chain of DESIGN_strength_combos.md §2, three keys joined by ">".
const CHAIN = "HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>SQUAT/GOBLET_SQUAT";

async function realCatalog() {
  const { readFile } = await import("node:fs/promises");
  return JSON.parse(await readFile(new URL("../exercises.json", import.meta.url), "utf8"));
}

test("a chain reads as its movements, each without its category unless the name is shared",
  async () => {
    const catalog = await realCatalog();
    assert.deepEqual(logic.chipsOf(catalog, CHAIN),
                     ["One arm swing", "Single arm dumbbell clean", "Goblet squat"]);
    assert.equal(logic.wordsOf(catalog, CHAIN),
                 "One arm swing → Single arm dumbbell clean → Goblet squat");
    // A plain exercise keeps its category, and so does a movement whose name a band
    // exercise shares (DESIGN_strength_combos.md D23).
    assert.deepEqual(logic.chipsOf(catalog, "SQUAT/GOBLET_SQUAT"), ["[Squat] Goblet squat"]);
    assert.equal(logic.wordsOf(catalog, "ROW/FACE_PULL>SQUAT/GOBLET_SQUAT"),
                 "[Row] Face pull → Goblet squat");
  });

test("a chain is per side when any movement is, and shows its first movement's photos",
  async () => {
    const catalog = await realCatalog();
    assert.equal(logic.perSideOf(catalog, CHAIN), true);
    assert.equal(logic.perSideOf(catalog, "HIP_RAISE/KETTLEBELL_SWING>SQUAT/GOBLET_SQUAT"), false);
    // A one-sided movement twice is once on each side inside the round (D16).
    const clean = "OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN";
    assert.equal(logic.perSideOf(catalog, `${clean}>SQUAT/GOBLET_SQUAT>${clean}`), false);
    assert.deepEqual(logic.photosOf(catalog, "SQUAT/GOBLET_SQUAT>HIP_RAISE/KETTLEBELL_SWING"),
                     logic.photosOf(catalog, "SQUAT/GOBLET_SQUAT"));
  });

test("a chip's three edits give the card its new key", () => {
  // Chain with on a plain exercise starts a chain.
  const swing = "HIP_RAISE/KETTLEBELL_SWING";
  const halo = "SHOULDER_STABILITY/KETTLEBELL_HALO";
  assert.equal(logic.chainAfter(swing, 0, halo), `${swing}>${halo}`);
  assert.equal(logic.chainAfter(CHAIN, 0, halo),
               `HIP_SWING/ONE_ARM_SWING>${halo}>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN`
               + ">SQUAT/GOBLET_SQUAT");
  assert.equal(logic.replacePart(CHAIN, 2, halo),
               `HIP_SWING/ONE_ARM_SWING>OLYMPIC_LIFT/SINGLE_ARM_DUMBBELL_CLEAN>${halo}`);
  // Removing a movement of two leaves a plain exercise.
  assert.equal(logic.removePart(`${swing}>${halo}`, 1), swing);
});

test("an edited chain keeps its sets, ticked or not, and loses its written load", () => {
  // DESIGN_strength_combos.md D22: the edit goes through `swapExercise`, as a swap does.
  const state = tickSet(exampleState(), 0, 0, 40);
  const key = logic.chainAfter(state.x[0].n, 0, "SQUAT/LEG_PRESS");
  const after = logic.swapExercise(state, 0, key);
  assert.equal(after.x[0].n, "SQUAT/BELT_SQUAT>SQUAT/LEG_PRESS");
  assert.deepEqual(after.x[0].sets, state.x[0].sets);
  assert.deepEqual(after.x[0].lines, [{ p: 1, s: 3, lo: 4, hi: 6, kg: null }]);
  assert.equal(logic.buildLog(after, END).x[0].n, key);
});
