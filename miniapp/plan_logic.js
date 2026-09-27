// The "Goals & plan" page's pure logic (DESIGN_calendar_miniapp.md §3.7): the mesocycles and
// goals in date order around a "Today" line, and what a tapped row opens. The snapshot is
// read like the calendar's. No DOM here, so `node --test` runs it.
import { shortDay } from "./calendar_logic.js?v=dev";

// Word for word the bot's `WHY_REQUEST` (cli/render/plan_page.py); a Python test holds the
// two together.
export const WHY_REQUEST = "plan_why";

export function planRows(snapshot) {
  const rows = [];
  (snapshot.meso || []).forEach((meso, index) => {
    rows.push({ kind: "meso", date: meso.s, index, name: meso.n, plan: meso.p,
                span: `${shortDay(meso.s)} – ${shortDay(meso.e)}`, summary: meso.m || "",
                done: meso.e < snapshot.today });
  });
  (snapshot.goals || []).forEach((goal) => {
    rows.push({ kind: "goal", date: goal.d, text: goal.t, description: goal.x || "",
                done: Boolean(goal.k) });
  });
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  // Today goes after every row that starts on or before it.
  let at = rows.findIndex((row) => row.date > snapshot.today);
  if (at === -1) {
    at = rows.length;
  }
  rows.splice(at, 0, { kind: "today", date: snapshot.today });
  // The rail beside each row: the mesocycle running on its date in that mesocycle's colour,
  // faded once it has ended. A goal or today inside a mesocycle keeps its colour.
  const mesos = snapshot.meso || [];
  for (const row of rows) {
    let index = row.index;
    if (row.kind !== "meso") {
      index = mesos.findIndex((meso) => meso.s <= row.date && row.date <= meso.e);
    }
    if (index === -1) {
      continue;
    }
    row.rail = { index, done: mesos[index].e < snapshot.today };
  }
  return rows;
}

export function rowSheet(row) {
  // What a tapped row opens: a mesocycle's dates and summary with the way to its reasoning
  // in the chat; a goal's line and description (§3.7).
  if (row.kind === "meso") {
    return { title: row.name, lines: [row.span, row.summary].filter(Boolean), why: true };
  }
  return { title: row.done ? "✅ Goal reached" : "🎯 Goal",
           lines: [row.text, row.description].filter(Boolean), why: false };
}

export function whyMessage(row) {
  // What `sendData` hands the bot: `plan show` of the tapped mesocycle's plan, which may be
  // another goal's than the next one (§3.7).
  return JSON.stringify({ [WHY_REQUEST]: row.plan });
}
