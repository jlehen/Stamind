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
// The version of both payloads: version 2 names an exercise by its key
// (DESIGN_exercise_table.md §8). The page draws no other session and sends no other log.
export const PAYLOAD_VERSION = 2;
// The version of the state saved on the phone. A state saved under another one is not read.
export const STATE_VERSION = 3;
export const OUT_OF_DATE = "This button is out of date. Send your coach any message and tap "
  + "the new one.";
// The same for a past log opened from the calendar: the athlete tapped a day there, not a button.
export const LOG_OUT_OF_DATE = "This log is out of date and cannot be opened.";
// How many changes Undo can take back, so the saved history stays small.
export const UNDO_DEPTH = 50;

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

// A past log rides after `l=`, encoded like the session, when the calendar opens the page on
// a day already logged (§8).
export function logFromHash(hash) {
  const match = /(?:^|[#&])l=([^&]+)/.exec(hash || "");
  if (!match) {
    return null;
  }
  return decodeSession(match[1]);
}

// The address the calendar's day sheet opens: `gym` is the day's `{ s, l }`, the session and
// the log the bot holds for it (§8).
export function loggedAddress(gym) {
  return `./index.html#s=${encodeSession(gym.s)}&l=${encodeSession(gym.l)}`;
}

// A button drawn before the exercise names became keys still carries a version 1 session, and
// the page tells the athlete so instead of drawing it (DESIGN_exercise_table.md §8). So does a
// past log from a month file built before then: its session is version 1 too.
export function isCurrent(session) {
  return Boolean(session) && session.v === PAYLOAD_VERSION;
}

// What the page says in place of a session it does not draw. `opened` is the past log the
// calendar opened the page on, or null when the gym button did.
export function outOfDateLine(opened) {
  return opened ? LOG_OUT_OF_DATE : OUT_OF_DATE;
}

export function demoSession() {
  // What the bare URL shows, so the page is testable without the bot (§2).
  return {
    v: PAYLOAD_VERSION,
    r: 0,
    d: "2026-09-24",
    t: "Gym: lower body strength",
    x: [
      { n: "SQUAT/BELT_SQUAT", s: 3, lo: 4, hi: 6, kg: 140 },
      { n: "DEADLIFT/ROMANIAN_DEADLIFT", s: 3, lo: 6, hi: 8, kg: 90 },
      { n: "SQUAT/LEG_PRESS", s: 3, lo: 8, hi: 10, kg: 200 },
      { n: "PULL_UP/PULL_UP", s: 3, lo: 6, hi: 8, kg: null },
      { n: "ROW/SEATED_CABLE_ROW", s: 3, lo: 10, hi: 12, kg: 57.5 },
      { n: "LUNGE/WALKING_LUNGE", s: 2, lo: 12, hi: 12, kg: 16 },
      { n: "SQUAT/LEG_EXTENSION", s: 3, lo: 12, hi: 15, kg: 45 },
      { n: "CALF_RAISE/CALF_RAISE", s: 3, lo: 12, hi: 15, kg: 60 },
    ],
    notes: "Alternate the belt squat and the pull-ups. Stop two reps short on the last set.",
  };
}

// ---------------------------------------------------------------------------------------
// The state the page keeps: the session, plus what the athlete has done to it.
// ---------------------------------------------------------------------------------------

// The clock does not run until `startClock`, so the athlete can change the exercises first (§1).
// Every card has an `id` that never changes, so a card's own undo finds it wherever it moved;
// "Start over" passes the next free one, so no new card reuses an id the undo history holds.
export function newState(session, firstId = 1) {
  const x = (session.x || []).map((row, index) => prescribedExercise(row, index + 1));
  x.forEach((exercise, index) => { exercise.id = firstId + index; });
  // A warm-up is a lighter entry of the same exercise (stamind/strength/progression.md).
  for (const exercise of x) {
    exercise.warmup = exercise.kg !== null && x.some(
      (other) => other.n === exercise.n && other.kg !== null && other.kg > exercise.kg);
  }
  return {
    v: STATE_VERSION,
    r: session.r,
    d: session.d,
    t: session.t || "Gym session",
    notes: session.notes || "",
    startedAt: null,
    // The start a timer reset threw away, which the next Start measures the ticked sets from.
    clockWas: null,
    finishedAt: null,
    note: "",
    nextId: firstId + x.length,
    x,
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

// The state of a session already logged (§8): what the page would hold had the athlete just
// sent `log`. The cards come in the log's order, each with its sets as done and then the
// written sets that were not; the written exercises the log does not hold come last, unticked.
export function stateFromLog(session, log) {
  const state = newState(session);
  const written = new Map(state.x.map((card) => [card.p, card]));
  state.x = [];
  for (const entry of log.x) {
    const done = entry.sets.map(([reps, kg, t]) => ({ reps, kg, done: true, t }));
    const card = written.get(entry.p);
    if (!card) {
      // An exercise the session did not ask for.
      insertAdded(state, state.x.length, entry.n, done, false);
      state.x[state.x.length - 1].note = entry.note || "";
      continue;
    }
    written.delete(entry.p);
    if (card.n !== entry.n) {
      // A swap: the written load was the other exercise's, as in `swapExercise`.
      card.n = entry.n;
      card.kg = null;
    }
    card.note = entry.note || "";
    card.sets = [...done, ...card.sets.slice(done.length)];
    state.x.push(card);
  }
  state.x.push(...written.values());
  state.note = log.note || "";
  state.finishedAt = clockMs(log.d, log.en);
  state.startedAt = clockMs(log.d, log.st);
  if (state.startedAt > state.finishedAt) {
    // The session ran over midnight, and `d` is the day it ended (§4).
    state.startedAt = clockMs(log.d, log.st, -1);
  }
  return state;
}

function clockMs(iso, clock, days = 0) {
  const [year, month, day] = iso.split("-").map(Number);
  const [hours, minutes] = clock.split(":").map(Number);
  return new Date(year, month - 1, day + days, hours, minutes).getTime();
}

export function storageKey(revision) {
  return `stamind-gym-v${STATE_VERSION}-r${revision}`;
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

function capitalise(name) {
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

// `at` is the index the new card takes: the end for "Add an exercise", the place after a card
// for that card's "Insert". `bodyweight` is the catalog's word on the exercise.
export function addExercise(state, name, bodyweight, at = state.x.length) {
  const kg = bodyweight ? null : ADDED_KG;
  const sets = [];
  for (let i = 0; i < ADDED_SETS; i += 1) {
    sets.push({ reps: ADDED_REPS, kg, done: false, t: null });
  }
  return insertAdded(next(state), at, name, sets, false);
}

// Dup: the card's exercise added right after it, with its sets as they stand and its label,
// none ticked. Like an inserted card, it stands for no written line (§1).
export function duplicateExercise(state, xi) {
  const source = state.x[xi];
  const sets = source.sets.map((set) => ({ reps: set.reps, kg: set.kg, done: false, t: null }));
  return insertAdded(next(state), xi + 1, source.n, sets, Boolean(source.warmup));
}

function insertAdded(after, at, name, sets, warmup) {
  const id = after.nextId;
  after.nextId += 1;
  after.x.splice(at, 0, { id, n: name, p: null, s: null, lo: null, hi: null, kg: null, note: "",
                          warmup, sets });
  return after;
}

// The card's "Warm-up" / "Main" label. The page shows it and the Markdown export writes it; the
// log does not carry it (§1).
export function toggleWarmup(state, xi) {
  const after = next(state);
  after.x[xi].warmup = !after.x[xi].warmup;
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
// After a timer reset, the sets already ticked keep their moment and are measured from the new
// start; one ticked before it counts as 0 (§1).
export function startClock(state, now) {
  if (state.startedAt) {
    return state;
  }
  const after = next(state);
  after.startedAt = now;
  if (after.clockWas !== null) {
    const shift = (after.clockWas - now) / 1000;
    for (const exercise of after.x) {
      for (const set of exercise.sets) {
        if (set.done && set.t !== null) {
          set.t = Math.max(0, Math.round(set.t + shift));
        }
      }
    }
    after.clockWas = null;
  }
  return after;
}

// The timer reset brings the Start button back, and takes the Finish with it: the next Finish
// sends a log with the new start and end, which replaces the one already sent (§4).
export function resetClock(state) {
  if (!state.startedAt) {
    return state;
  }
  const after = next(state);
  after.clockWas = after.startedAt;
  after.startedAt = null;
  after.finishedAt = null;
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
// Undo (§1). The history is a list of `{ state, card }`: the state before a change, and the id
// of the card the change was made on, or null for a change to the page as a whole. Undo never
// takes back a Finish: the sent log stays sent.
// ---------------------------------------------------------------------------------------

export function record(history, before, card) {
  return [...history, { state: before, card }].slice(-UNDO_DEPTH);
}

export function undoAll(history, state) {
  if (!history.length) {
    return null;
  }
  const restored = next(history[history.length - 1].state);
  restored.finishedAt = state.finishedAt;
  return { state: restored, history: history.slice(0, -1) };
}

export function canUndoCard(history, card) {
  return history.some((entry) => entry.card === card);
}

// Puts the card back as it was before its own last change, wherever it sits now, and leaves
// every other card alone. The states saved after that change still hold the card as it was,
// so they get its restored copy too, or an Undo further back would bring the change back.
export function undoCard(history, state, card) {
  const index = history.findLastIndex((entry) => entry.card === card);
  const xi = state.x.findIndex((exercise) => exercise.id === card);
  if (index < 0 || xi < 0) {
    return null;
  }
  const old = history[index].state.x.find((exercise) => exercise.id === card);
  const after = next(state);
  after.x[xi] = structuredClone(old);
  const kept = history.filter((_, i) => i !== index).map((entry, i) => {
    if (i < index) {
      return entry;
    }
    const patched = next(entry.state);
    const at = patched.x.findIndex((exercise) => exercise.id === card);
    if (at >= 0) {
      patched.x[at] = structuredClone(old);
    }
    return { state: patched, card: entry.card };
  });
  return { state: after, history: kept };
}

// ---------------------------------------------------------------------------------------
// The log payload (§4): one entry per exercise with at least one done set.
// ---------------------------------------------------------------------------------------

export function buildLog(state, now) {
  const end = clockAt(state, now);
  const log = {
    v: PAYLOAD_VERSION,
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
// The exercise catalog, `exercises.json` (DESIGN_exercise_table.md §8): one row per class, with
// its key `k`, its words `w`, its pattern `p`, its gear `g`, whether it is bodyweight `b`, and
// its photos id `f`. The page searches the words, prints them as `shown` writes them, and
// stores and sends the key.
// ---------------------------------------------------------------------------------------

// The words of "squat: belt squat" after the category, or all of them when there is none.
function nameAfterCategory(words) {
  const colon = words.indexOf(": ");
  return colon < 0 ? words : words.slice(colon + 2);
}

// A name that starts with the first typed word comes first, then a name that holds it, then an
// entry that matched through its category only.
function nameRank(name, first) {
  if (name.startsWith(first)) {
    return 0;
  }
  return name.includes(first) ? 1 : 2;
}

// The word "weighted" is left out of what is typed: a weighted twin is its class with a load.
// The hits are ranked on the name after the category, because every entry starts with its
// category and "curl" would otherwise fill the list with the curl category and hide "leg curl".
export function searchExercises(catalog, query, pattern) {
  const tokens = String(query || "").toLowerCase().split(/\s+/)
    .filter((token) => token && token !== "weighted");
  const scoped = pattern ? catalog.filter((row) => row.p === pattern) : catalog;
  if (!tokens.length && !pattern) {
    return [];
  }
  const first = tokens.length ? tokens[0] : "";
  const hits = scoped.filter((row) => tokens.every((token) => row.w.includes(token)))
    .map((row) => {
      const name = nameAfterCategory(row.w);
      return { row, name, rank: nameRank(name, first) };
    });
  hits.sort((a, b) => {
    if (a.rank !== b.rank) {
      return a.rank - b.rank;
    }
    if (a.name.length !== b.name.length) {
      return a.name.length - b.name.length;
    }
    if (a.row.w.length !== b.row.w.length) {
      return a.row.w.length - b.row.w.length;
    }
    return a.row.w < b.row.w ? -1 : 1;
  });
  return hits.slice(0, SEARCH_LIMIT).map((hit) => hit.row);
}

// Free Exercise DB serves its photos from its public repository (DESIGN_gym_logger.md §2).
export const PHOTO_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/";

// The words as the page prints them (DESIGN_exercise_table.md §8): "squat: belt squat" is
// "[Squat] Belt squat", and words with no category, "pull up", are "Pull up".
export function shown(words) {
  const colon = words.indexOf(": ");
  if (colon < 0) {
    return capitalise(words);
  }
  return `[${capitalise(words.slice(0, colon))}] ${capitalise(nameAfterCategory(words))}`;
}

// What the page prints for a key. A key the catalog lacks shows as it is.
export function wordsOf(catalog, key) {
  const row = catalog.find((entry) => entry.k === key);
  return row ? shown(row.w) : key;
}

export function photosOf(catalog, key) {
  const row = catalog.find((entry) => entry.k === key);
  if (!row || !row.f) {
    return [];
  }
  return [0, 1].map((index) => `${PHOTO_BASE}${row.f}/${index}.jpg`);
}

export function patternOf(catalog, key) {
  const row = catalog.find((entry) => entry.k === key);
  return row ? row.p : null;
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
