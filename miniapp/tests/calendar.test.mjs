// The calendar page's logic, checked against the snapshot in DESIGN_calendar_miniapp.md §5.
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../calendar_logic.js";

// A snapshot exactly as `calendar_page.pack` writes it: zlib, then base64url.
const PACKED = "eNqdkc1Kw0AUhV_lclctJDAzobVmp9S90O5CFmlzq6HJDGSSaigBQVy7cSn4bn0CH8E7aU2juHKVmTPn"
  + "uz8ne9xhKD1MKgxRCTX1xaWvJktxEQqFHlYmTZofTyxuSlP02sxXs874rUjpiykrdybJWfv8eH2GRZPvyFZU5km9gc"
  + "PTGxgNi1rDnNYgAxhlGqSEB6KtHZ9Yi2G0x-q_JdJ-HuXLANvYw4Ks6Ypqfruuszxlnx1sJyQLNBACga139F9RaVbZ"
  + "GlaJpSEmxS-MBTnr-pFOB-IxuowXivr60pE9NUWGOG-uvT8nrtztsZs7O4XBkIv2JrGNC4uPZtt1rNnGnzWGohuR_6y9"
  + "J3I9I7zNE62Jd46OiZ47wLKmEFw5KDlRF-5EQJFpjGN2z40mRx3eX6Aj_3DCqDE1pFkKgXL3MaNx27ZfKqWsMw";

// What Telegram does to the address: its own launch parameters around the page's own.
const TELEGRAM_HASH = `#tgWebAppData=query_id%3DAAH&c=${PACKED}&tgWebAppVersion=8.0`
  + "&tgWebAppPlatform=android";

test("c= is read next to Telegram's own parameters", async () => {
  assert.equal(logic.packedFromHash(TELEGRAM_HASH), PACKED);
  assert.equal(logic.packedFromHash(`#c=${PACKED}`), PACKED);
  assert.equal(logic.packedFromHash("#tgWebAppData=abc"), null);
  const snapshot = await logic.snapshotFromHash(TELEGRAM_HASH);
  assert.equal(snapshot.today, "2026-09-25");
  assert.equal(snapshot.meso[1].n, "Aerobic base");
  assert.deepEqual(snapshot.days["2026-09-22"].x, [{ i: "🏃", l: "Easy", g: "ok" }]);
  assert.equal(snapshot.days["2026-09-22"].sheet[1][1][0],
               "✅ 🏃 Easy run — 50 min (you did 32 min)");
});

test("no c= means no snapshot, and another version is refused", async () => {
  assert.equal(await logic.snapshotFromHash("#tgWebAppData=abc"), null);
  const bytes = new TextEncoder().encode(JSON.stringify({ v: 2 }));
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate"));
  const packed = Buffer.from(await new Response(stream).arrayBuffer()).toString("base64url");
  await assert.rejects(logic.snapshotFromHash(`#c=${packed}`), /version 2/);
});

test("the tint: green done, red missed, red wins, none ahead", () => {
  assert.deepEqual(logic.tint({ x: [{ i: "🏃", g: "ok" }] }), { kind: "ok", strength: 1 });
  assert.equal(logic.tint({ x: [{ i: "🏃", g: "miss" }] }).kind, "miss");
  assert.equal(logic.tint({ x: [{ i: "🏃", g: "less", r: 0.6 },
                                { i: "🏋️", g: "miss" }] }).kind, "miss");
  assert.equal(logic.tint({ x: [{ i: "🚴", g: "ahead" }] }), null);
  assert.equal(logic.tint(undefined), null);
});

test("a session off its plan is blue for less, orange for more, deeper the further", () => {
  // Tuesday: a 50-minute run cut to 32 minutes. Thursday: a 60-minute ride ridden at double.
  assert.deepEqual(logic.tint({ x: [{ i: "🏃", g: "less", r: 0.64 }] }),
                   { kind: "less", strength: Math.abs(Math.log2(0.64)) });
  assert.deepEqual(logic.tint({ x: [{ i: "🚴", g: "more", r: 2.4 }] }),
                   { kind: "more", strength: 1 });
  // Just past the tolerance still shows; a rest day trained through carries no ratio.
  assert.equal(logic.tint({ x: [{ i: "🚴", g: "more", r: 1.1 }] }).strength, 0.3);
  assert.deepEqual(logic.tint({ x: [{ i: "🛌", g: "more" }] }), { kind: "more", strength: 1 });
  // Two sessions: the one furthest from its plan sets the colour, over a green one.
  assert.deepEqual(logic.tint({ x: [{ i: "🏋️", g: "ok" }, { i: "🏃", g: "less", r: 0.8 },
                                    { i: "🚴", g: "more", r: 1.5 }] }),
                   { kind: "more", strength: Math.log2(1.5) });
});

test("two sessions show two icons and no label", () => {
  const one = logic.cellContent({ x: [{ i: "🚴", l: "Hills", g: "ahead" }], u: ["🥾"], c: 1,
                                  s: 0 });
  assert.deepEqual(one, { icons: ["🚴"], label: "Hills", faded: ["🥾"], constraint: true,
                          signal: false });
  const two = logic.cellContent({ x: [{ i: "🏃", l: "Easy", g: "ok" }, { i: "🏋️", g: "miss" }] });
  assert.deepEqual(two.icons, ["🏃", "🏋️"]);
  assert.equal(two.label, "");
  assert.deepEqual(logic.cellContent(undefined).icons, []);
});

test("the grid is Monday first and the window's months only", () => {
  const weeks = logic.monthWeeks({ year: 2026, month: 8 });
  assert.deepEqual(weeks[0], [null, "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                              "2026-09-05", "2026-09-06"]);
  assert.equal(weeks.at(-1)[2], "2026-09-30");
  assert.equal(weeks.at(-1)[3], null);
  const months = logic.monthsBetween("2026-08-28", "2026-11-06");
  assert.deepEqual(months.map(logic.monthTitle),
                   ["August 2026", "September 2026", "October 2026", "November 2026"]);
  assert.equal(logic.monthOf(months, "2026-09-25"), 1);
});

test("the strip, the end of the schedule, and the header words", async () => {
  const snapshot = await logic.snapshotFromHash(`#c=${PACKED}`);
  assert.equal(logic.mesoIndex(snapshot, "2026-09-30"), 0);
  assert.equal(logic.mesoIndex(snapshot, "2026-10-01"), 1);
  assert.equal(logic.mesoIndex(snapshot, "2026-10-19"), -1);
  assert.equal(logic.endNoteShown(snapshot, { year: 2026, month: 8 }), false);
  assert.equal(logic.endNoteShown(snapshot, { year: 2026, month: 9 }), true);
  assert.equal(logic.stamp(snapshot.at), "as of Fri 07:02");
  assert.equal(logic.END_NOTE, "That's the end of the current schedule.");
});

test("a day whose details did not fit says which days have them", async () => {
  const snapshot = await logic.snapshotFromHash(`#c=${PACKED}`);
  assert.equal(logic.sheetFor(snapshot, "2026-09-22").parts[0][0], "Planned");
  assert.equal(logic.sheetFor(snapshot, "2026-09-24"), null);
  assert.equal(logic.sheetFor(snapshot, "2026-08-30").missing,
               "This day's details did not fit. Days from 11 Sep to 16 Oct have them.");
  assert.equal(logic.sheetFor(snapshot, "2026-11-01"), null);
  assert.equal(logic.sheetFor(snapshot, "2026-12-01"), null);
});

test("a goal's day opens with the goal, even with nothing else on it", () => {
  const goal = { t: "🏃 Greifenseelauf — on 18 Oct (in 3 weeks)", d: "2026-10-18" };
  const planned = [["Planned", ["🏃 Today: Race — 60 min"]]];
  const snapshot = { today: "2026-09-25", from: "2026-08-28", to: "2026-11-06",
                     fit: ["2026-08-28", "2026-11-06"], goals: [goal],
                     days: { "2026-10-18": { x: [{ i: "🏃" }], sheet: planned } } };
  assert.deepEqual(logic.sheetFor(snapshot, "2026-10-18").parts,
                   [["Goal", [goal.t]], ...planned]);
  delete snapshot.days["2026-10-18"];
  assert.deepEqual(logic.sheetFor(snapshot, "2026-10-18").parts, [["Goal", [goal.t]]]);
  assert.equal(logic.sheetFor(snapshot, "2026-10-17"), null);
});

test("a day with a session can be asked for in full in the chat", async () => {
  const snapshot = await logic.snapshotFromHash(`#c=${PACKED}`);
  assert.equal(logic.asksForFullDay(snapshot, "2026-09-22"), true);
  assert.equal(logic.asksForFullDay(snapshot, "2026-09-24"), false);
  assert.equal(logic.fullDayMessage("2026-09-22"), '{"calendar_day":"2026-09-22"}');
});

test("the plan view runs mesocycles and goals in date order around today", async () => {
  const snapshot = await logic.snapshotFromHash(`#c=${PACKED}`);
  const rows = logic.planRows(snapshot);
  assert.deepEqual(rows.map((row) => row.kind), ["meso", "today", "meso", "goal"]);
  assert.equal(rows[0].span, "1 Sep – 30 Sep");
  assert.match(rows[3].text, /Sylvesterlauf/);
});
