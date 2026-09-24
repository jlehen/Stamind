// The gym logger's pure logic (DESIGN_gym_logger.md §3, §4): the two payloads, the state the
// page keeps between taps, and the log it sends back. No DOM here, so `node --test` runs it.

export const MAX_LOG_BYTES = 4096;
export const KG_STEP = 2.5;
export const REP_STEP = 1;
// An added exercise has no prescription, so it starts at three sets of eight; a loaded one
// starts at 20 kg and the athlete taps the number to type the real load.
export const ADDED_SETS = 3;
export const ADDED_REPS = 8;
export const ADDED_KG = 20;
export const SEARCH_LIMIT = 40;

const EN_DASH = "–";
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                "Dec"];

// ---------------------------------------------------------------------------------------
// The session payload (§3): base64url of UTF-8 JSON, carried in the URL hash.
// ---------------------------------------------------------------------------------------

export function encodeSession(session) {
  const bytes = new TextEncoder().encode(JSON.stringify(session));
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeSession(encoded) {
  const padded = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

export function sessionFromHash(hash) {
  // The hash is never sent to the host serving the page (§3), so it is where the session rides.
  const match = /(?:^|[#&])s=([^&]+)/.exec(hash || "");
  if (!match) {
    return null;
  }
  return decodeSession(match[1]);
}

export function demoSession() {
  // What the bare URL shows, so the page is testable without the bot (§2).
  return {
    v: 1,
    r: 0,
    d: "2026-09-24",
    t: "Gym: lower body strength",
    x: [
      { n: "belt squat", s: 3, lo: 4, hi: 6, kg: 140 },
      { n: "romanian deadlift", s: 3, lo: 6, hi: 8, kg: 90 },
      { n: "leg press", s: 3, lo: 8, hi: 10, kg: 200 },
      { n: "pull up", s: 3, lo: 6, hi: 8, kg: null },
      { n: "seated cable row", s: 3, lo: 10, hi: 12, kg: 57.5 },
      { n: "walking lunge", s: 2, lo: 12, hi: 12, kg: 16 },
      { n: "leg extension", s: 3, lo: 12, hi: 15, kg: 45 },
      { n: "calf raise", s: 3, lo: 12, hi: 15, kg: 60 },
    ],
    notes: "Alternate the belt squat and the pull-ups. Stop two reps short on the last set.",
  };
}

// ---------------------------------------------------------------------------------------
// The state the page keeps: the session, plus what the athlete has done to it.
// ---------------------------------------------------------------------------------------

// The clock does not run until `startClock`, so the athlete can change the exercises first (§1).
export function newState(session) {
  return {
    v: 1,
    r: session.r,
    d: session.d,
    t: session.t || "Gym session",
    notes: session.notes || "",
    startedAt: null,
    finishedAt: null,
    note: "",
    x: (session.x || []).map((row, index) => prescribedExercise(row, index + 1)),
  };
}

function prescribedExercise(row, position) {
  const count = Math.max(1, Number(row.s) || 1);
  const reps = clampReps(row.hi ?? row.lo ?? ADDED_REPS);
  const kg = row.kg ?? null;
  const sets = [];
  for (let i = 0; i < count; i += 1) {
    sets.push({ reps, kg, done: false, t: null });
  }
  return {
    n: row.n,
    p: position,
    s: count,
    lo: row.lo ?? null,
    hi: row.hi ?? null,
    kg,
    note: "",
    sets,
  };
}

export function storageKey(revision) {
  return `stamind-gym-v1-r${revision}`;
}

export function prescriptionLine(exercise) {
  if (exercise.s === null) {
    return "added";
  }
  const lo = exercise.lo;
  const hi = exercise.hi;
  let reps = "";
  if (lo !== null && hi !== null && lo !== hi) {
    reps = `${lo}${EN_DASH}${hi}`;
  } else if (lo !== null || hi !== null) {
    reps = String(hi ?? lo);
  }
  const scheme = reps ? `${exercise.s}×${reps}` : `${exercise.s} sets`;
  if (exercise.kg === null) {
    return scheme;
  }
  return `${scheme} @ ${formatKg(exercise.kg)} kg`;
}

export function formatKg(kg) {
  if (kg === null) {
    return "BW";
  }
  return String(Math.round(kg * 100) / 100);
}

export function capitalise(name) {
  if (!name) {
    return "";
  }
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function clampReps(reps) {
  const value = Math.round(Number(reps));
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(999, Math.max(1, value));
}

function clampKg(kg) {
  if (kg === null) {
    return null;
  }
  const value = Number(kg);
  if (!Number.isFinite(value) || value < 0) {
    return null;
  }
  return Math.round(value * 100) / 100;
}

// ---------------------------------------------------------------------------------------
// The actions. Each one takes the state and returns the next one; the page saves it and
// redraws.
// ---------------------------------------------------------------------------------------

function next(state) {
  return structuredClone(state);
}

export function setReps(state, xi, si, reps) {
  const after = next(state);
  after.x[xi].sets[si].reps = clampReps(reps);
  return after;
}

export function bumpReps(state, xi, si, delta) {
  return setReps(state, xi, si, state.x[xi].sets[si].reps + delta);
}

export function setKg(state, xi, si, kg) {
  const after = next(state);
  after.x[xi].sets[si].kg = clampKg(kg);
  return after;
}

export function bumpKg(state, xi, si, delta) {
  const current = state.x[xi].sets[si].kg;
  // Bodyweight is below zero: one tap down from 0 kg goes back to BW, one tap up leaves it.
  if (current === null) {
    return setKg(state, xi, si, delta > 0 ? KG_STEP : null);
  }
  const value = current + delta;
  return setKg(state, xi, si, value < 0 ? null : value);
}

export function toggleDone(state, xi, si, seconds) {
  const after = next(state);
  const set = after.x[xi].sets[si];
  set.done = !set.done;
  set.t = set.done ? Math.max(0, Math.round(seconds)) : null;
  return after;
}

export function addSet(state, xi) {
  const after = next(state);
  const sets = after.x[xi].sets;
  const last = sets[sets.length - 1];
  sets.push({ reps: last ? last.reps : ADDED_REPS, kg: last ? last.kg : null, done: false,
              t: null });
  return after;
}

export function removeSet(state, xi) {
  if (state.x[xi].sets.length <= 1) {
    return state;
  }
  const after = next(state);
  after.x[xi].sets.pop();
  return after;
}

export function swapExercise(state, xi, name) {
  const after = next(state);
  const exercise = after.x[xi];
  exercise.n = name;
  // The row's position carries over so the ingest knows what this stood for (§4); its written
  // load does not, because it was the other exercise's load.
  exercise.kg = null;
  return after;
}

export function addExercise(state, name, equipment) {
  const after = next(state);
  const kg = equipment === "bodyweight" ? null : ADDED_KG;
  const sets = [];
  for (let i = 0; i < ADDED_SETS; i += 1) {
    sets.push({ reps: ADDED_REPS, kg, done: false, t: null });
  }
  after.x.push({ n: name, p: null, s: null, lo: null, hi: null, kg: null, note: "", sets });
  return after;
}

export function removeExercise(state, xi) {
  const after = next(state);
  after.x.splice(xi, 1);
  return after;
}

export function moveExercise(state, xi, delta) {
  const target = xi + delta;
  if (target < 0 || target >= state.x.length) {
    return state;
  }
  const after = next(state);
  const [moved] = after.x.splice(xi, 1);
  after.x.splice(target, 0, moved);
  return after;
}

export function setExerciseNote(state, xi, text) {
  const after = next(state);
  after.x[xi].note = text;
  return after;
}

export function setSessionNote(state, text) {
  const after = next(state);
  after.note = text;
  return after;
}

// ---------------------------------------------------------------------------------------
// Finishing (§4): the first Finish stops the clock. The log, and every set ticked after it,
// carry that moment, so an edited log sent again replaces the first instead of adding one.
// ---------------------------------------------------------------------------------------

// The Start button starts the clock, and so does the first ticked set if the athlete forgot it.
export function startClock(state, now) {
  if (state.startedAt) {
    return state;
  }
  const after = next(state);
  after.startedAt = now;
  return after;
}

export function clockAt(state, now) {
  return state.finishedAt ?? now;
}

export function markFinished(state, now) {
  if (state.finishedAt) {
    return state;
  }
  const after = next(state);
  after.finishedAt = now;
  return after;
}

// ---------------------------------------------------------------------------------------
// The log payload (§4): one entry per exercise with at least one done set.
// ---------------------------------------------------------------------------------------

export function buildLog(state, now) {
  const end = clockAt(state, now);
  const log = {
    v: 1,
    r: state.r,
    // The day the athlete lifted, from the phone's clock, which can differ from the session's
    // date when they train early or late; `r` still says which session this stood for.
    d: localDate(end),
    st: formatClock(state.startedAt),
    en: formatClock(end),
    x: [],
  };
  for (const exercise of state.x) {
    const done = exercise.sets.filter((set) => set.done);
    if (!done.length) {
      continue;
    }
    const entry = { n: exercise.n };
    if (exercise.p !== null && exercise.p !== undefined) {
      entry.p = exercise.p;
    }
    entry.sets = done.map((set) => [set.reps, set.kg, set.t ?? 0]);
    if (exercise.note && exercise.note.trim()) {
      entry.note = exercise.note.trim();
    }
    log.x.push(entry);
  }
  if (state.note && state.note.trim()) {
    log.note = state.note.trim();
  }
  return log;
}

export function logText(log) {
  return JSON.stringify(log);
}

export function byteLength(text) {
  return new TextEncoder().encode(text).length;
}

export function finish(state, now) {
  // `sendData` caps the message at 4,096 bytes (§4), so the page checks before it sends.
  const log = buildLog(state, now);
  const text = logText(log);
  const bytes = byteLength(text);
  return { log, text, bytes, fits: bytes <= MAX_LOG_BYTES };
}

export function doneSetCount(state) {
  let count = 0;
  for (const exercise of state.x) {
    count += exercise.sets.filter((set) => set.done).length;
  }
  return count;
}

export function lastSetSeconds(state) {
  let last = 0;
  for (const exercise of state.x) {
    for (const set of exercise.sets) {
      if (set.done && set.t !== null && set.t > last) {
        last = set.t;
      }
    }
  }
  return last;
}

// ---------------------------------------------------------------------------------------
// The exercise search, over `exercises.json` (§2).
// ---------------------------------------------------------------------------------------

export function searchExercises(catalog, query, pattern) {
  const tokens = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  const scoped = pattern ? catalog.filter((row) => row.p === pattern) : catalog;
  if (!tokens.length && !pattern) {
    return [];
  }
  const hits = scoped.filter((row) => tokens.every((token) => row.n.includes(token)));
  const first = tokens.length ? tokens[0] : "";
  hits.sort((a, b) => {
    const starts = Number(b.n.startsWith(first)) - Number(a.n.startsWith(first));
    if (starts) {
      return starts;
    }
    if (a.n.length !== b.n.length) {
      return a.n.length - b.n.length;
    }
    return a.n < b.n ? -1 : 1;
  });
  return hits.slice(0, SEARCH_LIMIT);
}

// Free Exercise DB serves its photos from its public repository (DESIGN_gym_logger.md §2).
export const PHOTO_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/";

export function photosOf(catalog, name) {
  const row = catalog.find((entry) => entry.n === name);
  if (!row || !row.f) {
    return [];
  }
  return [0, 1].map((index) => `${PHOTO_BASE}${row.f}/${index}.jpg`);
}

export function patternOf(catalog, name) {
  const row = catalog.find((entry) => entry.n === name);
  return row ? row.p : null;
}

export function equipmentOf(catalog, name) {
  const row = catalog.find((entry) => entry.n === name);
  return row ? row.e : null;
}

// ---------------------------------------------------------------------------------------
// Clock and date, all local (§4: `st` and `en` are local clock times).
// ---------------------------------------------------------------------------------------

export function formatClock(ms) {
  const when = new Date(ms);
  return `${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

export function localDate(ms) {
  const when = new Date(ms);
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

export function formatDay(iso) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
  if (!parts) {
    return String(iso || "");
  }
  const when = new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
  return `${DAYS[when.getDay()]} ${MONTHS[when.getMonth()]} ${when.getDate()}`;
}

export function formatMMSS(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  return `${pad(Math.floor(whole / 60))}:${pad(whole % 60)}`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}
