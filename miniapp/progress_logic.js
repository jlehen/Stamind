// The Progress page's pure logic (DESIGN_progress_page.md §3): the spans, what the chart
// draws, the week lines and the record cards. Today is the file's, never the phone's, and
// every word is the one the file carries; the page formats only numbers (choice 9). No DOM
// here, so `node --test` runs it.
import { isoDay, parseDay, shortDay } from "./calendar_logic.js?v=dev";

// What the page says when it has nothing to show (§3).
export const COULD_NOT_LOAD =
  "Your progress could not be loaded. Close this page and tap again in a moment.";
export const NO_BUTTON = "Open this page from the bot's 📈 Progress button.";

// The line under the chart (§3.1). Fatigue is named though not drawn (choice 3).
export const CHART_NOTE = "Fitness: what your last six weeks of training built. Fatigue: what "
  + "your last week or so cost. Form: fitness minus fatigue; above zero you are fresh.";

export const TABS = [
  { key: "fitness", label: "Fitness" },
  { key: "weeks", label: "Weeks" },
  { key: "mesocycles", label: "Mesocycles" },
];

// The spans under the tabs (choice 1). `weeks` counts this week, as `sm progress -w` does.
export const SPANS = [
  { key: "4w", label: "4 weeks", weeks: 4 },
  { key: "3m", label: "3 months", weeks: 13 },
  { key: "plan", label: "This plan" },
  { key: "all", label: "Everything" },
];
export const FIRST_TAB = "fitness";
export const FIRST_SPAN = "3m";

// ---------------------------------------------------------------------------------------
// Dates and numbers.
// ---------------------------------------------------------------------------------------

export function shiftDay(iso, days) {
  const date = parseDay(iso);
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

export function monday(iso) {
  return shiftDay(iso, -((parseDay(iso).getDay() + 6) % 7));
}

export function dayNumber(iso) {
  // Whole days since 1970, free of the phone's time zone.
  const [year, month, day] = iso.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86400000;
}

export function hours(seconds) {
  // "1h24", the hours of a week.
  const minutes = Math.round((seconds || 0) / 60);
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

function overlaps(start, end, span) {
  return start <= span.to && end >= span.from;
}

// ---------------------------------------------------------------------------------------
// The spans (§3).
// ---------------------------------------------------------------------------------------

export function governingPlan(file) {
  // The plan that governs today: its mesocycles are the bands that are not inferred.
  const bands = (file.mesocycles || []).filter((band) => band.source === "plan");
  if (!bands.length) {
    return null;
  }
  return { from: bands[0].start_date, to: bands[bands.length - 1].end_date };
}

export function spansOffered(file) {
  // "This plan" only when a plan governs today.
  return SPANS.filter((span) => span.key !== "plan" || governingPlan(file));
}

export function spanDates(file, key) {
  // The days a span covers. Under 4 weeks and 3 months the chart ends with next week, under
  // the plan and everything at the last day written (choice 2).
  const days = file.days || [];
  const last = days.length ? days[days.length - 1].date : file.today;
  const span = SPANS.find((one) => one.key === key);
  if (span && span.weeks) {
    const thisMonday = monday(file.today);
    return { from: shiftDay(thisMonday, -7 * (span.weeks - 1)), to: shiftDay(thisMonday, 13) };
  }
  const plan = governingPlan(file);
  if (key === "plan" && plan) {
    return { from: plan.from, to: last < plan.to ? last : plan.to };
  }
  return { from: days.length ? days[0].date : file.today, to: last };
}

// ---------------------------------------------------------------------------------------
// Fitness (§3.1): the lines, the bars, the bands and the goals of one span.
// ---------------------------------------------------------------------------------------

function lineSegments(days, field, today) {
  // One run of points per stretch with a value, cut where the value is missing and where
  // the measured past gives way to the projection, which is drawn dashed.
  const segments = [];
  let current = null;
  for (const day of days) {
    const value = day[field];
    if (value === null || value === undefined) {
      current = null;
      continue;
    }
    const dashed = day.date > today;
    if (current && current.dashed !== dashed) {
      const joint = current.points[current.points.length - 1];
      current = { dashed, points: [joint] };
      segments.push(current);
    }
    if (!current) {
      current = { dashed, points: [] };
      segments.push(current);
    }
    current.points.push([day.date, value]);
  }
  return segments;
}

export function chart(file, key) {
  const span = spanDates(file, key);
  const days = (file.days || []).filter((day) => day.date >= span.from && day.date <= span.to);
  const weeks = (file.weeks || []).filter((week) => overlaps(week.monday,
                                                             shiftDay(week.monday, 6), span));
  const values = [0];
  for (const day of days) {
    for (const field of ["ctl", "tsb"]) {
      if (day[field] !== null && day[field] !== undefined) {
        values.push(day[field]);
      }
    }
  }
  const bars = weeks.map((week) => ({
    monday: week.monday, planned: week.planned, done: week.ahead ? null : week.done,
    label: week.ahead || !week.hours_done ? "" : hours(week.hours_done),
  }));
  // Each band keeps its place in the file's list, so its colour does not change with the span.
  const bands = [];
  (file.mesocycles || []).forEach((band, index) => {
    if (!overlaps(band.start_date, band.end_date, span)) {
      return;
    }
    const start = [band.start_date, span.from].sort()[1];
    const end = [band.end_date, span.to].sort()[0];
    bands.push({ index, name: band.label, start, end });
  });
  return {
    from: span.from, to: span.to, today: file.today,
    fitness: lineSegments(days, "ctl", file.today),
    form: lineSegments(days, "tsb", file.today),
    low: Math.min(...values), high: Math.max(...values),
    bars, most: Math.max(1, ...bars.map((bar) => Math.max(bar.planned || 0, bar.done || 0))),
    bands,
    goals: (file.goals || []).filter((goal) => goal.date >= span.from && goal.date <= span.to)
      .map((goal) => ({ ...goal, text: `🎯 ${goal.title}, ${shortDay(goal.date)}` })),
  };
}

export function xAt(model, iso, width) {
  // Where a day starts across the chart; the day after `to` is the right edge.
  const first = dayNumber(model.from);
  return (dayNumber(iso) - first) / (dayNumber(model.to) + 1 - first) * width;
}

// ---------------------------------------------------------------------------------------
// Weeks (§3.2): newest first, the week under way first and never graded.
// ---------------------------------------------------------------------------------------

function sportWords(sport) {
  if (sport.sessions) {
    return `${sport.icon} ${Math.round(sport.done)} of ${Math.round(sport.written)}`;
  }
  if (sport.percent === null) {
    return `${sport.icon} done ${Math.round(sport.done)}`;
  }
  return `${sport.icon} ${sport.percent}%`;
}

export function weekRows(file, key) {
  const span = spanDates(file, key);
  const rows = [];
  const now = (file.weeks || []).find((week) => week.under_way);
  if (now) {
    rows.push({ kind: "now", text: `This week so far: ${hours(now.hours_done)}` });
  }
  for (const week of [...(file.weeks || [])].reverse()) {
    if (!week.grade || !overlaps(week.monday, shiftDay(week.monday, 6), span)) {
      continue;
    }
    rows.push({
      kind: "week", label: `${shortDay(week.monday)}:`,
      parts: week.grade.map((sport) => ({ text: sportWords(sport), short: sport.short })),
      lines: week.grade.flatMap((sport) => [
        { text: `${sport.icon} ${sport.line}`, short: sport.short },
        ...sport.changed.map((text) => ({ text, under: true })),
      ]),
    });
  }
  return rows;
}

// ---------------------------------------------------------------------------------------
// Mesocycles (§3.3): every record newest first, under the mesocycle under way.
// ---------------------------------------------------------------------------------------

function dates(start, end) {
  return `${shortDay(start)} – ${shortDay(end)}`;
}

export function recordCards(file, key) {
  const span = spanDates(file, key);
  const cards = [];
  const current = (file.mesocycles || []).find((band) => band.source === "plan"
    && band.start_date <= file.today && file.today <= band.end_date);
  if (current && overlaps(current.start_date, current.end_date, span)) {
    cards.push({ head: `${current.label}, ${dates(current.start_date, current.end_date)}`,
                 status: "under way", lines: [] });
  }
  for (const record of file.records || []) {
    if (!overlaps(record.start, record.end, span)) {
      continue;
    }
    const card = { head: `${record.name}, ${dates(record.start, record.end)}`,
                   status: record.ended, lines: [] };
    if (!record.first) {
      card.lines = ["not written yet"];
      cards.push(card);
      continue;
    }
    card.lines = [record.first];
    if (record.said) {
      card.lines.push(`“${record.said}”`);
    }
    // A tap opens the whole record, and the athlete's answer under it (choice 15).
    card.sheet = { title: record.name,
                   lines: [record.first, ...record.lines, record.answer].filter(Boolean) };
    cards.push(card);
  }
  return cards;
}
