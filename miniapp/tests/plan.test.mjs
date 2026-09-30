// The "Goals & plan" page's logic (DESIGN_calendar_miniapp.md §3.7).
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../plan_logic.js";

// It is Wednesday 30 September. The build mesocycle is behind, the base one is running, and
// the 10k in October is done while the Sylvesterlauf is ahead.
const SNAPSHOT = {
  v: 1, at: "2026-09-30T07:02", today: "2026-09-30",
  meso: [
    { n: "Build", s: "2026-09-01", e: "2026-09-28", p: 6 },
    { n: "Aerobic base", s: "2026-09-29", e: "2026-10-25", p: 10,
      m: "Rebuild the aerobic base and start sprint intervals." },
  ],
  goals: [
    { t: "🏃 Autumn 10k — on Sun Sep 27 (passed)", d: "2026-09-27", k: 1 },
    { t: "🏃 Sylvesterlauf — on Sun Dec 13 (in 11 weeks)", d: "2026-12-13",
      x: "Run under 50 minutes." },
  ],
};

test("mesocycles and goals run in date order around today", () => {
  const rows = logic.planRows(SNAPSHOT);
  assert.deepEqual(rows.map((row) => row.kind), ["meso", "goal", "meso", "today", "goal"]);
  assert.equal(rows[0].span, "1 Sep – 28 Sep");
  // Build ended on the 28th, so it is greyed like the reached goal; base is still running.
  assert.equal(rows[0].done, true);
  assert.equal(rows[2].done, false);
  assert.equal(rows[1].done, true);
  assert.equal(rows[4].done, false);
});

test("the rail keeps a mesocycle's colour through a goal or today inside its dates", () => {
  const rows = logic.planRows(SNAPSHOT);
  // Build: its own stretch, ended. Today falls in the base mesocycle, still running.
  assert.deepEqual(rows[0].rail, { index: 0, done: true });
  assert.deepEqual(rows[3].rail, { index: 1, done: false });
  // The 10k on 27 September fell in Build. The Sylvesterlauf is past every mesocycle.
  assert.deepEqual(rows[1].rail, { index: 0, done: true });
  assert.equal(rows[4].rail, undefined);
});

test("a mesocycle opens its dates, its summary and the way to the chat", () => {
  const [build, , base] = logic.planRows(SNAPSHOT);
  assert.deepEqual(logic.rowSheet(base), {
    title: "Aerobic base",
    lines: ["29 Sep – 25 Oct", "Rebuild the aerobic base and start sprint intervals."],
    why: true,
  });
  // A plan written before summaries existed still offers the chat.
  assert.deepEqual(logic.rowSheet(build).lines, ["1 Sep – 28 Sep"]);
  assert.equal(logic.rowSheet(build).why, true);
});

test("a goal opens its line and its description", () => {
  const rows = logic.planRows(SNAPSHOT);
  assert.deepEqual(logic.rowSheet(rows[4]), {
    title: "🎯 Goal",
    lines: ["🏃 Sylvesterlauf — on Sun Dec 13 (in 11 weeks)", "Run under 50 minutes."],
    why: false,
  });
  assert.equal(logic.rowSheet(rows[1]).title, "✅ Goal reached");
});

test("the why names the tapped mesocycle's plan, not the next goal's", () => {
  const [build, , base] = logic.planRows(SNAPSHOT);
  assert.equal(logic.whyMessage(base), '{"plan_why":10}');
  assert.equal(logic.whyMessage(build), '{"plan_why":6}');
});

test("from the plan file, a mesocycle shows its long text and no chat button", () => {
  const file = { ...SNAPSHOT, meso: SNAPSHOT.meso.map((meso) => ({ ...meso, f: "Why it is." })) };
  const row = logic.planRows(file).find((r) => r.kind === "meso" && r.name === "Aerobic base");
  assert.deepEqual(logic.rowSheet(row, true), {
    title: "Aerobic base", why: false,
    lines: ["29 Sep – 25 Oct", "Rebuild the aerobic base and start sprint intervals.",
            "Why it is."],
  });
  assert.equal(logic.rowSheet(row).why, true);
});
