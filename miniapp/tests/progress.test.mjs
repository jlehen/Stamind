// The Progress page's logic (DESIGN_progress_page.md §3).
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "../progress_logic.js";

// It is Thursday 12 November. Two weeks have ended, a third is under way, and the sessions
// are written to Sunday 22 November. The plan that governs today runs from 4 November to
// 20 December; a mesocycle `data bootstrap` inferred comes before it.
function days() {
  const out = [];
  for (let date = "2026-10-26"; date <= "2026-11-22"; date = logic.shiftDay(date, 1)) {
    const planned = date > "2026-11-12";
    out.push({ date, load: 30, source: planned ? "planned" : "actual",
               ctl: date === "2026-10-26" ? null : 20, atl: 25, tsb: -5 });
  }
  return out;
}

const RIDE_SHORT = {
  sport: "cycling", icon: "🚴", sessions: false, written: 190, done: 156, percent: 82,
  short: true, line: "cycling: written 190, done 156 (82%), short",
  changed: ["Sat 7 Nov Easy Gravel Ride (Deload): cut from 120 to 40 min"],
};
const GYM_SHORT = {
  sport: "strength_training", icon: "🏋️", sessions: true, written: 2, done: 1, percent: 50,
  short: true, line: "strength_training: written 2 sessions, done 1, short", changed: [],
};
const RIDE_OVER = { ...RIDE_SHORT, written: 100, done: 108, percent: 108, short: false,
                    line: "cycling: written 100, done 108 (108%)", changed: [] };

const FILE = {
  v: 1, at: "2026-11-12T07:02", today: "2026-11-12",
  days: days(),
  weeks: [
    { monday: "2026-10-26", planned: 100, done: 108, hours_planned: 18000, hours_done: 19800,
      meso: "~Base", under_way: false, ahead: false, grade: [RIDE_OVER] },
    { monday: "2026-11-02", planned: 237, done: 190, hours_planned: 25200, hours_done: 21060,
      meso: "Build", under_way: false, ahead: false, grade: [RIDE_SHORT, GYM_SHORT] },
    { monday: "2026-11-09", planned: 120, done: 60, hours_planned: 9000, hours_done: 5040,
      meso: "Build", under_way: true, ahead: false },
    { monday: "2026-11-16", planned: 250, done: 0, hours_planned: 27000, hours_done: 0,
      meso: "Build", under_way: false, ahead: true },
  ],
  records: [
    { name: "Race-Specific Sharpening", start: "2026-10-25", end: "2026-11-03",
      ended: "cut short by a new plan",
      first: "Sessions 5 of 9 · load 237 of 275 TSS · 5h51 · fitness 16 -> 18 · no test",
      said: "You kept your runs going strong.",
      lines: ["The athlete completed 5 of 9 sessions."], answer: 'Athlete: "felt fresh"' },
    { name: "Base", start: "2026-10-05", end: "2026-10-24", ended: "finished" },
  ],
  goals: [{ title: "Sylvesterlauf", date: "2026-12-20" }],
  mesocycles: [
    { label: "~Base", source: "inferred", start_date: "2026-09-01", end_date: "2026-11-03" },
    { label: "Build", source: "plan", start_date: "2026-11-04", end_date: "2026-11-29" },
    { label: "Peak", source: "plan", start_date: "2026-11-30", end_date: "2026-12-20" },
  ],
};

test("the page opens on Fitness and 3 months, and offers four spans with a plan", () => {
  assert.equal(logic.FIRST_TAB, "fitness");
  assert.equal(logic.FIRST_SPAN, "3m");
  assert.deepEqual(logic.spansOffered(FILE).map((span) => span.label),
                   ["4 weeks", "3 months", "This plan", "Everything"]);
});

test("with no plan, This plan is not offered", () => {
  const file = { ...FILE, mesocycles: FILE.mesocycles.slice(0, 1) };
  assert.deepEqual(logic.spansOffered(file).map((span) => span.key), ["4w", "3m", "all"]);
});

test("4 weeks and 3 months end with next week; the plan and everything at the last day "
     + "written (choice 2)", () => {
  assert.deepEqual(logic.spanDates(FILE, "4w"), { from: "2026-10-19", to: "2026-11-22" });
  assert.deepEqual(logic.spanDates(FILE, "3m"), { from: "2026-08-17", to: "2026-11-22" });
  assert.deepEqual(logic.spanDates(FILE, "plan"), { from: "2026-11-04", to: "2026-11-22" });
  assert.deepEqual(logic.spanDates(FILE, "all"), { from: "2026-10-26", to: "2026-11-22" });
  // Sessions written for a month ahead: 3 months still ends with next week.
  const later = { ...FILE, days: [...FILE.days, { date: "2026-12-20", ctl: 30, tsb: 4 }] };
  assert.equal(logic.spanDates(later, "3m").to, "2026-11-22");
  assert.equal(logic.spanDates(later, "all").to, "2026-12-20");
  assert.equal(logic.spanDates(later, "plan").to, "2026-12-20");
});

test("today is the file's, never the phone's", () => {
  // The file was built on Sunday evening; the phone reads Monday.
  const sunday = { ...FILE, today: "2026-11-15" };
  assert.equal(logic.spanDates(sunday, "4w").to, "2026-11-22");
  const monday = { ...FILE, today: "2026-11-16" };
  assert.equal(logic.spanDates(monday, "4w").to, "2026-11-29");
  assert.equal(logic.chart(sunday, "4w").today, "2026-11-15");
});

test("the chart draws fitness and form, the projection dashed, and no fatigue", () => {
  const model = logic.chart(FILE, "all");
  // The first day is in the warm-up, with no fitness: the line starts the day after.
  assert.equal(model.fitness[0].points[0][0], "2026-10-27");
  assert.deepEqual(model.fitness.map((segment) => segment.dashed), [false, true]);
  // The projection starts where the past ends, so the line has no gap.
  assert.equal(model.fitness[1].points[0][0], "2026-11-12");
  assert.equal(model.form.length, 2);
  assert.equal("fatigue" in model, false);
  assert.equal(model.low, -5);
  assert.equal(model.high, 20);
});

test("the bars: planned beside done, the hours done over each, none ahead", () => {
  const bars = logic.chart(FILE, "all").bars;
  assert.deepEqual(bars.map((bar) => bar.label), ["5h30", "5h51", "1h24", ""]);
  assert.equal(bars[3].done, null);
  assert.equal(bars[3].planned, 250);
  assert.equal(logic.chart(FILE, "all").most, 250);
});

test("the bands are cut to the span, and a goal outside it is no mark", () => {
  const model = logic.chart(FILE, "4w");
  assert.deepEqual(model.bands.map((band) => [band.index, band.name, band.start, band.end]), [
    [0, "~Base", "2026-10-19", "2026-11-03"],
    [1, "Build", "2026-11-04", "2026-11-22"],
  ]);
  assert.deepEqual(model.goals, []);
  const all = logic.chart({ ...FILE, days: [...FILE.days, { date: "2026-12-20" }] }, "all");
  assert.deepEqual(all.goals.map((goal) => goal.text), ["🎯 Sylvesterlauf, 20 Dec"]);
});

test("a day maps across the chart's width, the day after the span its right edge", () => {
  const model = { from: "2026-11-01", to: "2026-11-10" };
  assert.equal(logic.xAt(model, "2026-11-01", 100), 0);
  assert.equal(logic.xAt(model, "2026-11-06", 100), 50);
  assert.equal(logic.xAt(model, "2026-11-11", 100), 100);
});

test("the weeks: this week's hours first, then each ended week newest first", () => {
  const rows = logic.weekRows(FILE, "all");
  assert.deepEqual(rows.map((row) => row.kind), ["now", "week", "week"]);
  assert.equal(rows[0].text, "This week so far: 1h24");
  assert.equal(rows[1].label, "2 Nov:");
  assert.deepEqual(rows[1].parts, [{ text: "🚴 82%", short: true },
                                   { text: "🏋️ 1 of 2", short: true }]);
  assert.deepEqual(rows[2].parts, [{ text: "🚴 108%", short: false }]);
});

test("a week opens on the terminal's lines, a short sport's sessions under it", () => {
  const [, week] = logic.weekRows(FILE, "all");
  assert.deepEqual(week.lines, [
    { text: "🚴 cycling: written 190, done 156 (82%), short", short: true },
    { text: "Sat 7 Nov Easy Gravel Ride (Deload): cut from 120 to 40 min", under: true },
    { text: "🏋️ strength_training: written 2 sessions, done 1, short", short: true },
  ]);
});

test("the span picks the weeks", () => {
  const rows = logic.weekRows(FILE, "plan");
  assert.deepEqual(rows.map((row) => row.label || row.text),
                   ["This week so far: 1h24", "2 Nov:"]);
});

test("the mesocycles: the one under way first, then every record newest first", () => {
  const cards = logic.recordCards(FILE, "all");
  assert.deepEqual(cards.map((card) => [card.head, card.status]), [
    ["Build, 4 Nov – 29 Nov", "under way"],
    ["Race-Specific Sharpening, 25 Oct – 3 Nov", "cut short by a new plan"],
  ]);
  assert.deepEqual(cards[1].lines, [FILE.records[0].first, "“You kept your runs going strong.”"]);
  assert.equal(cards[0].sheet, undefined);
});

test("a record opens whole, the athlete's answer under it; one not written yet says so", () => {
  const cards = logic.recordCards(FILE, "3m");
  assert.deepEqual(cards[1].sheet, {
    title: "Race-Specific Sharpening",
    lines: [FILE.records[0].first, "The athlete completed 5 of 9 sessions.",
            'Athlete: "felt fresh"'],
  });
  assert.deepEqual([cards[2].head, cards[2].lines], ["Base, 5 Oct – 24 Oct",
                                                      ["not written yet"]]);
  assert.equal(cards[2].sheet, undefined);
});

// Cycling in power zones: one week measured, one trained but not recorded, the week under
// way, and next week as prescribed; two mesocycles' average weeks.
const ZONES = [{
  sport: "cycling", currency: "power", tag: "[pwr]",
  zone_labels: ["recovery", "endurance", "tempo", "threshold", "VO2max", "anaerobic",
                "neuromuscular"],
  weeks: [
    { week_commencing: "2026-10-26", future: false, seconds: [600, 7200, 1200, 0, 0, 0, 0],
      undercounted: false },
    { week_commencing: "2026-11-02", future: false, seconds: null, undercounted: true },
    { week_commencing: "2026-11-09", future: false, seconds: [300, 1800, 0, 0, 0, 0, 0],
      undercounted: false },
    { week_commencing: "2026-11-16", future: true, seconds: [0, 9000, 0, 600, 0, 0, 0],
      undercounted: false },
  ],
  mesocycles: [
    { name: "Sharpening", start: "2026-10-05", end: "2026-11-03", focus: "Race pace.",
      weeks: 4, seconds: [600, 6000, 900, 300, 0, 0, 0] },
    { name: "Build", start: "2026-11-04", end: "2026-11-29", focus: "Long bouts.", weeks: 1,
      seconds: [300, 1800, 0, 0, 0, 0, 0] },
  ],
}];

test("intensity by week: the span's weeks, measured, prescribed ahead, and the marks", () => {
  const [chart] = logic.intensity({ ...FILE, zones: ZONES }, "4w", "week");
  assert.equal(chart.head, "cycling [pwr]");
  assert.equal(chart.labels.length, 7);
  assert.deepEqual(chart.items.map((item) => [item.monday, item.mark, item.ahead]), [
    ["2026-10-26", "", false], ["2026-11-02", "!", false], ["2026-11-09", "", false],
    ["2026-11-16", "+", true],
  ]);
  assert.equal(chart.most, 9600);
  assert.deepEqual(chart.marks, ["!", "+"]);
});

test("the toggle: by mesocycle, an average week per mesocycle the span overlaps", () => {
  const file = { ...FILE, zones: ZONES };
  const [chart] = logic.intensity(file, "all", "meso");
  assert.deepEqual(chart.items.map((item) => [item.name, item.per]), [
    ["Sharpening", "a week, over 4 weeks"], ["Build", "a week, over 1 week"],
  ]);
  assert.equal(chart.items[0].focus, "Race pace.");
  // The plan's span starts on 4 November: the mesocycle before it is left out, and a
  // sport's zones stay the same.
  const [planned] = logic.intensity(file, "plan", "meso");
  assert.deepEqual(planned.items.map((item) => item.name), ["Build"]);
  assert.equal(planned.head, chart.head);
});

test("a file with no zones has no chart, the tab's empty state", () => {
  assert.deepEqual(logic.intensity(FILE, "3m", "week"), []);
  assert.deepEqual(logic.intensity({ ...FILE, zones: [] }, "3m", "meso"), []);
  assert.deepEqual(logic.TABS.map((tab) => tab.label),
                   ["Fitness", "Weeks", "Mesocycles", "Intensity"]);
  assert.equal(logic.FIRST_GRAIN, "week");
});

test("hours read as the chat says them", () => {
  assert.equal(logic.hours(5040), "1h24");
  assert.equal(logic.hours(2700), "0h45");
  assert.equal(logic.hours(null), "0h00");
});
