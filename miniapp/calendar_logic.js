// The calendar page's pure logic (DESIGN_calendar_miniapp.md §3, §5): reading the snapshot out
// of the address, the month grid, the tint and the day sheet, and folding in the files from
// the bucket (DESIGN_miniapp_storage.md §7.1). No DOM here, so `node --test` runs it.

export const VERSION = 1;

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
                     "September", "October", "November", "December"];

// Word for word the bot's `SIMPLE_END_NOTE` (cli/render/plan_lines.py); a Python test holds
// the two together.
export const END_NOTE = "That's the end of the current schedule.";

// ---------------------------------------------------------------------------------------
// The snapshot (§5): zlib, then base64url, after `c=` in the part of the address after '#'.
// ---------------------------------------------------------------------------------------

export function packedFromHash(hash) {
  // Telegram adds its own launch parameters after the '#', so `c=` is found among them.
  const match = /(?:^|[#&])c=([^&]+)/.exec(hash || "");
  return match ? match[1] : null;
}

export function base64urlBytes(encoded) {
  const padded = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export async function inflate(bytes) {
  // "deflate" is the zlib format Python's `zlib.compress` writes.
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new TextDecoder().decode(await new Response(stream).arrayBuffer());
}

export async function snapshotFromHash(hash) {
  const packed = packedFromHash(hash);
  if (!packed) {
    return null;
  }
  const snapshot = JSON.parse(await inflate(base64urlBytes(packed)));
  if (snapshot.v !== VERSION) {
    throw new Error(`The calendar says version ${snapshot.v}, and this page reads ${VERSION}.`);
  }
  return snapshot;
}

// ---------------------------------------------------------------------------------------
// Dates. Every date is a YYYY-MM-DD string, read at noon so no time zone moves it a day.
// ---------------------------------------------------------------------------------------

export function parseDay(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
}

export function isoDay(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function shortDay(iso) {
  // "11 Sep", the words the "did not fit" message and the legend use.
  const date = parseDay(iso);
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function monthTitle(month) {
  return `${MONTH_NAMES[month.month]} ${month.year}`;
}

export function stamp(at) {
  // "as of Fri 07:02": when the bot built the button (§1).
  const [day, time] = at.split("T");
  return `as of ${DAYS[parseDay(day).getDay()]} ${time}`;
}

export function staleNote(snapshot, phoneDay) {
  // A copy from an earlier day than the phone's marks the wrong day as today (§5).
  if (phoneDay <= snapshot.today) {
    return null;
  }
  return `This calendar is from ${DAYS[parseDay(snapshot.today).getDay()]} `
    + `${shortDay(snapshot.today)}.`;
}

export function later(one, other) {
  // The stamp a page shows: the later of the button's time and the file's (storage §7.1).
  return one > other ? one : other;
}

export function monthsBetween(from, to) {
  // The months the page can swipe through: those of the window, no further (§1).
  const months = [];
  const first = parseDay(from);
  const last = parseDay(to);
  let year = first.getFullYear();
  let month = first.getMonth();
  while (year < last.getFullYear() || (year === last.getFullYear() && month <= last.getMonth())) {
    months.push({ year, month });
    month += 1;
    if (month === 12) {
      month = 0;
      year += 1;
    }
  }
  return months;
}

export function reachableMonths(data) {
  // The window's months, or every month that has a file once the index file arrived
  // (storage §7.1).
  if (data.first && data.last) {
    return monthsBetween(`${data.first}-01`, `${data.last}-01`);
  }
  return monthsBetween(data.from, data.to);
}

export function monthOf(months, iso) {
  // Which of `months` holds `iso`; the first when none does.
  const date = parseDay(iso);
  const found = months.findIndex((m) => m.year === date.getFullYear()
    && m.month === date.getMonth());
  return Math.max(0, found);
}

export function monthWeeks(month) {
  // The month as weeks of seven dates, Monday first; a day of another month is null (§1).
  const first = new Date(month.year, month.month, 1, 12);
  const lead = (first.getDay() + 6) % 7;
  const count = new Date(month.year, month.month + 1, 0, 12).getDate();
  const cells = Array(lead).fill(null);
  for (let day = 1; day <= count; day += 1) {
    cells.push(isoDay(new Date(month.year, month.month, day, 12)));
  }
  while (cells.length % 7) {
    cells.push(null);
  }
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }
  return weeks;
}

// ---------------------------------------------------------------------------------------
// One day's cell (§3.1, §3.2).
// ---------------------------------------------------------------------------------------

// The palest a session off its plan gets, so a gap just past the tolerance still shows.
const PALEST = 0.3;

export function gapStrength(session) {
  // 0.3 to 1 as the gap grows: full at half the plan or double it. A rest day trained
  // through carries no ratio and is full.
  if (session.r === undefined) {
    return 1;
  }
  return Math.min(1, Math.max(PALEST, Math.abs(Math.log2(session.r))));
}

export function tint(day) {
  // A missed session wins; then the session furthest from its plan; then green; none
  // while everything is ahead (§3.2).
  const sessions = (day && day.x) || [];
  if (sessions.some((session) => session.g === "miss")) {
    return { kind: "miss", strength: 1 };
  }
  let furthest = null;
  for (const session of sessions) {
    if (session.g !== "less" && session.g !== "more") {
      continue;
    }
    const strength = gapStrength(session);
    if (!furthest || strength > furthest.strength) {
      furthest = { kind: session.g, strength };
    }
  }
  if (furthest) {
    return furthest;
  }
  if (sessions.some((session) => session.g === "ok")) {
    return { kind: "ok", strength: 1 };
  }
  return null;
}

export function cellContent(day) {
  // The icons, and the label only when the day holds one session (§3.1).
  const sessions = (day && day.x) || [];
  return {
    icons: sessions.map((session) => session.i),
    label: sessions.length === 1 ? sessions[0].l || "" : "",
    faded: (day && day.u) || [],
    constraint: Boolean(day && day.c),
    signal: Boolean(day && day.s),
  };
}

export function legendFor(snapshot, month) {
  // The mesocycles that touch the month shown, each with its place in the one list
  // (storage §4).
  const first = isoDay(new Date(month.year, month.month, 1, 12));
  const last = isoDay(new Date(month.year, month.month + 1, 0, 12));
  return (snapshot.meso || []).map((meso, index) => ({ meso, index }))
    .filter(({ meso }) => meso.s <= last && first <= meso.e);
}

export function mesoIndex(snapshot, iso) {
  // The strip's colour is the mesocycle's place in the one list (§4); -1 outside them all.
  return (snapshot.meso || []).findIndex((meso) => meso.s <= iso && iso <= meso.e);
}

export function goalsOn(snapshot, iso) {
  return (snapshot.goals || []).filter((goal) => goal.d === iso);
}

export function pastTheEnd(snapshot, iso) {
  return Boolean(snapshot.end) && iso > snapshot.end;
}

export function endNoteShown(snapshot, month) {
  // The note sits under every month that holds a day past the end of the schedule (§5).
  if (!snapshot.end) {
    return false;
  }
  const last = isoDay(new Date(month.year, month.month + 1, 0, 12));
  return last > snapshot.end;
}

// ---------------------------------------------------------------------------------------
// The day sheet (§1, §5).
// ---------------------------------------------------------------------------------------

export function inWindow(snapshot, iso) {
  return snapshot.from <= iso && iso <= snapshot.to;
}

export function isOutside(snapshot, iso) {
  // A day the page holds no data for: outside the button's window, in a month whose file
  // has not arrived.
  return !inWindow(snapshot, iso) && !monthLoaded(snapshot, iso);
}

// The heading of the part a goal's day opens with (§3.5).
export const GOAL = "Goal";

export function sheetFor(snapshot, iso) {
  // The day's sheet, opening with the goals set on that day (§3.5).
  const found = daySheet(snapshot, iso);
  const goals = goalsOn(snapshot, iso).map((goal) => goal.t);
  if (!goals.length) {
    return found;
  }
  return { ...found, parts: [[GOAL, goals], ...((found && found.parts) || [])] };
}

function daySheet(snapshot, iso) {
  // The sheet; or, for a day whose details did not fit, the message saying which days have
  // them; or null for a day with nothing to say.
  const day = snapshot.days[iso];
  if (day && day.sheet) {
    return { parts: day.sheet };
  }
  // A month's file holds every sheet, so a day without one has nothing to say (storage §4).
  if (monthLoaded(snapshot, iso)) {
    return null;
  }
  // An empty day past the end of the schedule never had anything to fit.
  if (!inWindow(snapshot, iso) || (!day && pastTheEnd(snapshot, iso))) {
    return null;
  }
  const fit = snapshot.fit;
  if (fit && fit[0] <= iso && iso <= fit[1]) {
    return null;
  }
  return { missing: didNotFit(fit) };
}

// Word for word the bot's `DAY_REQUEST` (cli/render/calendar_page.py); a Python test holds
// the two together.
export const DAY_REQUEST = "calendar_day";

export function asksForFullDay(snapshot, iso) {
  // "💬 Full day in chat" sits under a day that holds a session (§6), for as long as its
  // month's file has not arrived (storage §7.1, D4).
  const day = snapshot.days[iso];
  return Boolean(day && day.x && day.x.length) && !monthLoaded(snapshot, iso);
}

export function fullDayMessage(iso) {
  // What `sendData` hands the bot: the one day to post in the chat (§6).
  return JSON.stringify({ [DAY_REQUEST]: iso });
}

export function didNotFit(fit) {
  if (!fit) {
    return "This day's details did not fit.";
  }
  return `This day's details did not fit. Days from ${shortDay(fit[0])} to `
    + `${shortDay(fit[1])} have them.`;
}

// ---------------------------------------------------------------------------------------
// The files from the bucket (DESIGN_miniapp_storage.md §7.1). The page keeps one set of
// data, which starts as the button's; `loaded` holds the state of each month's file.
// ---------------------------------------------------------------------------------------

export const LOADING = "loading";
export const LOADED = "loaded";
export const FAILED = "failed";

export function monthKey(month) {
  return `${month.year}-${String(month.month + 1).padStart(2, "0")}`;
}

export function monthLabel(month) {
  // Word for word `calendar_page.month_label`: the label September's file is named from.
  return `calendar/${monthKey(month)}`;
}

function monthLoaded(snapshot, iso) {
  return (snapshot.loaded || {})[iso.slice(0, 7)] === LOADED;
}

export function withIndex(data, index) {
  // The index file's fields replace the button's: today, the goals, the mesocycles, the
  // last day of the schedule, and the months it has files for. The stamp keeps the later
  // of the two times.
  return { ...data, ...index, end: index.end, at: later(data.at, index.at) };
}

export function withMonthState(data, key, state) {
  return { ...data, loaded: { ...data.loaded, [key]: state } };
}

export function withMonth(data, key, file) {
  // A month file's days replace that month's days.
  const days = {};
  for (const [iso, day] of Object.entries(data.days)) {
    if (iso.slice(0, 7) !== key) {
      days[iso] = day;
    }
  }
  return withMonthState({ ...data, days: { ...days, ...file.days } }, key, LOADED);
}

export function monthNote(data, month) {
  // What sits under the grid while a month's file is on its way, or when it could not be
  // had; nothing once it arrived, or when the page has no files at all.
  const state = (data.loaded || {})[monthKey(month)];
  if (state === LOADING) {
    return "Loading…";
  }
  if (state === FAILED) {
    return "This month could not be loaded.";
  }
  return "";
}
