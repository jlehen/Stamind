// The gym logger's DOM layer (DESIGN_gym_logger.md §1): it draws the session, and hands every
// tap to `logic.js`, which owns the state and the two payloads.
// "?v=dev" becomes the commit at deploy, like the addresses in index.html (§2).
import * as logic from "./logic.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
// `telegram-web-app.js` loads in a plain browser too, and there it reports platform "unknown".
const inTelegram = Boolean(tg && tg.platform && tg.platform !== "unknown");

function telegramHas(version) {
  // Calling a method the Telegram client is too old for throws and prints an error, so every
  // call below asks first.
  return Boolean(tg && typeof tg.isVersionAtLeast === "function" && tg.isVersionAtLeast(version));
}

const ui = {
  title: document.getElementById("title"),
  day: document.getElementById("day"),
  tally: document.getElementById("tally"),
  headNotes: document.getElementById("head-notes"),
  restValue: document.getElementById("rest-value"),
  restLabel: document.getElementById("rest-label"),
  rest: document.getElementById("rest"),
  startClock: document.getElementById("start-clock"),
  undo: document.getElementById("undo"),
  resetClock: document.getElementById("reset-clock"),
  cards: document.getElementById("cards"),
  sessionNote: document.getElementById("session-note"),
  addExercise: document.getElementById("add-exercise"),
  finish: document.getElementById("finish"),
  sent: document.getElementById("sent"),
  reset: document.getElementById("reset"),
  searchSheet: document.getElementById("search-sheet"),
  searchTitle: document.getElementById("search-title"),
  searchInput: document.getElementById("search-input"),
  searchAll: document.getElementById("search-all"),
  searchAllRow: document.getElementById("search-all-row"),
  searchResults: document.getElementById("search-results"),
  searchClose: document.getElementById("search-close"),
  outputSheet: document.getElementById("output-sheet"),
  outputHint: document.getElementById("output-hint"),
  outputNote: document.getElementById("output-note"),
  outputText: document.getElementById("output-text"),
  outputCopy: document.getElementById("output-copy"),
  outputClose: document.getElementById("output-close"),
};

// The 4,096-byte cap on one `sendData` message, in the digits the athlete reads (§4).
const LIMIT = logic.MAX_LOG_BYTES.toLocaleString("en-US");

// How long the page waits for Telegram to take the log and close the app, and what it says
// when that does not happen.
const SEND_WATCHDOG_MS = 600;
const SEND_FAILED = "Telegram did not take the log. Copy it and send it to the bot as a "
  + "message.";

let catalog = [];
// The exercises whose photos are open. Not saved: they close when the page reloads.
const photosOpen = new Set();
let state = null;
// What Undo takes back, oldest first (`logic.record`). Saved beside the state.
let history = [];
let storeKey = "";
// What the search sheet is for: "swap" or "insert" the card at `searchIndex`, or "add" one.
let searchMode = "add";
let searchIndex = null;
let swapPattern = null;

// ---------------------------------------------------------------------------------------
// Saving. Telegram's own device storage when the app has it, the browser's otherwise (§1).
// ---------------------------------------------------------------------------------------

function deviceStore() {
  // DeviceStorage arrived in Bot API 9.0; its methods answer through a (error, value) callback.
  // The object exists in every client, so the version is what says whether it works.
  if (!telegramHas("9.0") || !tg.DeviceStorage) {
    return null;
  }
  return {
    get: (key) => new Promise((resolve) => {
      try {
        tg.DeviceStorage.getItem(key, (error, value) => resolve(error ? null : value));
      } catch (problem) {
        console.warn("DeviceStorage.getItem failed", problem);
        resolve(null);
      }
    }),
    set: (key, value) => {
      try {
        tg.DeviceStorage.setItem(key, value, () => {});
      } catch (problem) {
        console.warn("DeviceStorage.setItem failed", problem);
      }
    },
    remove: (key) => {
      try {
        tg.DeviceStorage.removeItem(key, () => {});
      } catch (problem) {
        console.warn("DeviceStorage.removeItem failed", problem);
      }
    },
  };
}

const browserStore = {
  get: (key) => new Promise((resolve) => {
    try {
      resolve(window.localStorage.getItem(key));
    } catch (problem) {
      console.warn("localStorage.getItem failed", problem);
      resolve(null);
    }
  }),
  set: (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch (problem) {
      console.warn("localStorage.setItem failed", problem);
    }
  },
  remove: (key) => {
    try {
      window.localStorage.removeItem(key);
    } catch (problem) {
      console.warn("localStorage.removeItem failed", problem);
    }
  },
};

const store = deviceStore() || browserStore;

function persist() {
  store.set(storeKey, JSON.stringify(state));
  store.set(`${storeKey}-undo`, JSON.stringify(history));
}

// ---------------------------------------------------------------------------------------
// Applying a change. `apply` redraws, `applyQuiet` does not, because a redraw triggered by a
// field losing focus would replace the button the tap was heading for. Both record the change
// for Undo, under the card it was made on (`card`, its id) or under the page (null).
// ---------------------------------------------------------------------------------------

function remember(after, card) {
  if (after !== state) {
    history = logic.record(history, state, card);
  }
  state = after;
  persist();
}

function apply(after, card = null) {
  remember(after, card);
  render();
}

function applyQuiet(after, card = null) {
  remember(after, card);
  tick();
}

// Finish is the one change Undo does not take back (§1), so it goes around the history.
function applyUnrecorded(after) {
  state = after;
  persist();
  render();
}

function undo(result) {
  if (!result) {
    return;
  }
  state = result.state;
  history = result.history;
  persist();
  render();
}

// ---------------------------------------------------------------------------------------
// Small DOM builders.
// ---------------------------------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function button(label, className, onClick) {
  const node = el("button", className, label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

// ---------------------------------------------------------------------------------------
// Drawing.
// ---------------------------------------------------------------------------------------

function render() {
  ui.title.textContent = state.t;
  ui.day.textContent = `for ${logic.formatDay(state.d)}`;
  ui.headNotes.textContent = state.notes || "";
  ui.headNotes.hidden = !state.notes;
  if (ui.sessionNote.value !== state.note) {
    ui.sessionNote.value = state.note;
  }
  ui.cards.replaceChildren(...state.x.map(exerciseCard));
  const finished = Boolean(state.finishedAt);
  ui.sent.hidden = !finished;
  if (finished) {
    ui.sent.textContent = `Sent at ${logic.formatClock(state.finishedAt)}. You can still edit: `
      + "Send again replaces that log.";
  }
  setFinishLabel(finished ? "Send again" : "Finish");
  ui.undo.disabled = !history.length;
  tick();
}

function setFinishLabel(label) {
  ui.finish.textContent = label;
  if (inTelegram) {
    tg.MainButton.setText(label);
  }
}

function exerciseCard(exercise, xi) {
  const card = el("section", "card");
  const id = exercise.id;

  const head = el("div", "card-head");
  const name = el("div", "card-name");
  name.append(el("div", "card-title", logic.capitalise(exercise.n)));
  name.append(el("div", "card-pres", logic.prescriptionLine(exercise)));
  head.append(name);
  const moves = el("div", "moves");
  moves.append(button("↑", "move", () => apply(logic.moveExercise(state, xi, -1))));
  moves.append(button("↓", "move", () => apply(logic.moveExercise(state, xi, 1))));
  head.append(moves);
  card.append(head);

  const photos = logic.photosOf(catalog, exercise.n);
  if (photosOpen.has(exercise.n)) {
    const strip = el("div", "photos");
    for (const address of photos) {
      const photo = el("img");
      photo.src = address;
      photo.alt = `${exercise.n}, photo`;
      photo.loading = "lazy";
      strip.append(photo);
    }
    card.append(strip);
  }

  exercise.sets.forEach((set, si) => card.append(setRow(exercise, xi, set, si)));

  const tools = el("div", "tools");
  const undoCard = button("↶ Undo", "pill undo", () => undo(logic.undoCard(history, state, id)));
  undoCard.disabled = !logic.canUndoCard(history, id);
  undoCard.setAttribute("aria-label", `Undo the last change to ${exercise.n}`);
  tools.append(undoCard);
  tools.append(button("+ Set", "pill", () => apply(logic.addSet(state, xi), id)));
  tools.append(button("− Set", "pill", () => apply(logic.removeSet(state, xi), id)));
  // ↻ rather than ⇄: this puts another exercise here, it does not trade two cards (§1).
  tools.append(button("↻ Swap", "pill", () => openSearch("swap", xi)));
  tools.append(button("⤵ Insert", "pill", () => openSearch("insert", xi)));
  tools.append(button("✕ Remove", "pill danger", () => apply(logic.removeExercise(state, xi))));
  if (photos.length) {
    const label = photosOpen.has(exercise.n) ? "Hide photos" : "Photos";
    tools.append(button(label, "pill", () => togglePhotos(exercise.n)));
  }
  card.append(tools);

  const note = el("input", "note");
  note.type = "text";
  note.placeholder = "Note on this exercise";
  note.value = exercise.note || "";
  note.addEventListener("change",
    () => applyQuiet(logic.setExerciseNote(state, xi, note.value), id));
  card.append(note);
  return card;
}

function togglePhotos(name) {
  if (photosOpen.has(name)) {
    photosOpen.delete(name);
  } else {
    photosOpen.add(name);
  }
  render();
}

function setRow(exercise, xi, set, si) {
  const id = exercise.id;
  const row = el("div", set.done ? "set done" : "set");
  row.append(el("div", "set-index", String(si + 1)));

  row.append(stepper({
    value: String(set.reps),
    unit: "reps",
    onMinus: () => apply(logic.bumpReps(state, xi, si, -logic.REP_STEP), id),
    onPlus: () => apply(logic.bumpReps(state, xi, si, logic.REP_STEP), id),
    onType: (text, field) => {
      applyQuiet(logic.setReps(state, xi, si, parseFloat(text)), id);
      field.value = String(state.x[xi].sets[si].reps);
    },
  }));

  row.append(stepper({
    value: logic.formatKg(set.kg),
    unit: "kg",
    onMinus: () => apply(logic.bumpKg(state, xi, si, -logic.KG_STEP), id),
    onPlus: () => apply(logic.bumpKg(state, xi, si, logic.KG_STEP), id),
    onType: (text, field) => {
      const typed = text.trim() === "" || /^bw$/i.test(text.trim()) ? null : parseFloat(text);
      applyQuiet(logic.setKg(state, xi, si, typed), id);
      field.value = logic.formatKg(state.x[xi].sets[si].kg);
    },
  }));

  const check = button("✓", "tick", () => {
    // A set ticked before Start starts the clock, so its time is 0 rather than lost (§1).
    const started = logic.startClock(state, Date.now());
    apply(logic.toggleDone(started, xi, si, secondsNow(started)), id);
  });
  check.setAttribute("aria-pressed", String(set.done));
  check.setAttribute("aria-label", set.done ? `Set ${si + 1} done` : `Mark set ${si + 1} done`);
  row.append(check);
  return row;
}

function stepper(spec) {
  const box = el("div", "stepper");
  box.append(button("−", "step", spec.onMinus));
  const field = el("input", "num");
  field.type = "text";
  field.inputMode = "decimal";
  field.value = spec.value;
  field.setAttribute("aria-label", spec.unit);
  field.addEventListener("focus", () => field.select());
  field.addEventListener("change", () => spec.onType(field.value, field));
  box.append(field);
  box.append(button("+", "step", spec.onPlus));
  return box;
}

function secondsNow(at = state) {
  // After Finish the clock stands still (§4), so a set ticked later is stamped at the finish.
  return (logic.clockAt(at, Date.now()) - at.startedAt) / 1000;
}

function tick() {
  const done = logic.doneSetCount(state);
  ui.tally.textContent = done === 1 ? "· 1 set done" : `· ${done} sets done`;
  const started = Boolean(state.startedAt);
  ui.startClock.hidden = started;
  ui.rest.hidden = !started;
  ui.resetClock.hidden = !started;
  if (!started) {
    return;
  }
  if (state.finishedAt) {
    ui.restLabel.textContent = "in total";
    ui.restValue.textContent = logic.formatMMSS(secondsNow());
    return;
  }
  const last = logic.lastSetSeconds(state);
  ui.restLabel.textContent = done ? "since last set" : "since start";
  ui.restValue.textContent = logic.formatMMSS(secondsNow() - last);
}

// ---------------------------------------------------------------------------------------
// The exercise search: a swap keeps the card's movement pattern as its filter, an added or
// inserted exercise searches everything (§1).
// ---------------------------------------------------------------------------------------

function openSearch(mode, xi = null) {
  searchMode = mode;
  searchIndex = xi;
  swapPattern = mode === "swap" ? logic.patternOf(catalog, state.x[xi].n) : null;
  ui.searchTitle.textContent = searchTitle(mode, xi);
  ui.searchAllRow.hidden = !swapPattern;
  ui.searchAll.checked = !swapPattern;
  ui.searchInput.value = "";
  ui.searchSheet.hidden = false;
  renderResults();
  ui.searchInput.focus();
}

function searchTitle(mode, xi) {
  if (mode === "swap") {
    return "Swap exercise";
  }
  if (mode === "insert") {
    return `Insert after ${state.x[xi].n}`;
  }
  return "Add an exercise";
}

function closeSearch() {
  ui.searchSheet.hidden = true;
}

function renderResults() {
  const pattern = ui.searchAll.checked ? null : swapPattern;
  const hits = logic.searchExercises(catalog, ui.searchInput.value, pattern);
  if (!hits.length) {
    ui.searchResults.replaceChildren(el("p", "empty", "Type a few letters of the exercise."));
    return;
  }
  ui.searchResults.replaceChildren(...hits.map((row) => {
    const hit = button("", "result", () => choose(row));
    hit.append(el("span", "result-name", logic.capitalise(row.n)));
    hit.append(el("span", "result-kind", `${row.p.replace(/_/g, " ")} · ${row.e}`));
    return hit;
  }));
}

function choose(row) {
  closeSearch();
  if (searchMode === "swap") {
    apply(logic.swapExercise(state, searchIndex, row.n), state.x[searchIndex].id);
    return;
  }
  if (searchMode === "insert") {
    apply(logic.addExercise(state, row.n, row.e, searchIndex + 1));
    return;
  }
  apply(logic.addExercise(state, row.n, row.e));
}

// ---------------------------------------------------------------------------------------
// Finishing: build the log, check it fits, send it or show it (§4).
// ---------------------------------------------------------------------------------------

function onFinish() {
  const now = Date.now();
  const result = logic.finish(state, now);
  if (!result.log.x.length) {
    say("No set is ticked yet, so there is nothing to send.");
    return;
  }
  if (!result.fits) {
    say(`This log is ${result.bytes} bytes and Telegram accepts ${LIMIT}. `
        + "Shorten the notes, or remove an exercise you did not do.");
    return;
  }
  // The first Finish stops the clock (§4); a log sent again after an edit ends at the same
  // moment, and the bot replaces the earlier one instead of adding a second.
  applyUnrecorded(logic.markFinished(state, now));
  if (inTelegram) {
    try {
      tg.sendData(result.text);
      // A taken message closes the app, so a page still here after 600 ms means the log
      // never left, and the athlete gets the same sheet to copy from.
      window.setTimeout(() => showOutput(result, SEND_FAILED), SEND_WATCHDOG_MS);
      return;
    } catch (problem) {
      console.warn("sendData failed", problem);
    }
  }
  showOutput(result);
}

function showOutput(result, hint) {
  ui.outputHint.textContent = hint || "";
  ui.outputHint.hidden = !hint;
  ui.outputNote.textContent = `${result.bytes} bytes of the ${LIMIT} Telegram allows. `
    + "Copy this into a file and run: sm strength ingest <file>";
  ui.outputText.value = result.text;
  ui.outputSheet.hidden = false;
}

function copyOutput() {
  ui.outputText.select();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ui.outputText.value).then(
      () => { ui.outputCopy.textContent = "Copied"; },
      () => { ui.outputCopy.textContent = "Select and copy"; },
    );
    return;
  }
  ui.outputCopy.textContent = "Select and copy";
}

function say(message) {
  if (inTelegram && typeof tg.showAlert === "function") {
    tg.showAlert(message);
    return;
  }
  window.alert(message);
}

function ask(message, onYes) {
  if (inTelegram && typeof tg.showConfirm === "function") {
    tg.showConfirm(message, (yes) => {
      if (yes) {
        onYes();
      }
    });
    return;
  }
  if (window.confirm(message)) {
    onYes();
  }
}

function startOver() {
  ask("Throw away everything logged here and start from the written session? Undo brings it "
      + "back.", () => apply(logic.newState(sessionFromUrl(), state.nextId)));
}

// ---------------------------------------------------------------------------------------
// Start-up.
// ---------------------------------------------------------------------------------------

function sessionFromUrl() {
  try {
    const session = logic.sessionFromHash(window.location.hash);
    if (session) {
      return session;
    }
  } catch (problem) {
    console.warn("the session in the URL could not be read", problem);
  }
  // A bare URL shows the demo session, so the page can be opened without the bot (§2).
  return logic.demoSession();
}

async function loadCatalog() {
  try {
    const answer = await fetch("./exercises.json");
    return await answer.json();
  } catch (problem) {
    console.warn("exercises.json could not be read", problem);
    return [];
  }
}

async function restore(session) {
  const saved = await store.get(logic.storageKey(session.r));
  if (!saved) {
    return logic.newState(session);
  }
  try {
    const parsed = JSON.parse(saved);
    // A saved state for this revision wins over the URL, so a reopened app carries on (§1).
    if (parsed && parsed.v === 2 && parsed.r === session.r && Array.isArray(parsed.x)) {
      return parsed;
    }
  } catch (problem) {
    console.warn("the saved session could not be read", problem);
  }
  return logic.newState(session);
}

function wire() {
  ui.sessionNote.addEventListener("change",
    () => applyQuiet(logic.setSessionNote(state, ui.sessionNote.value)));
  ui.addExercise.addEventListener("click", () => openSearch("add"));
  ui.startClock.addEventListener("click", () => apply(logic.startClock(state, Date.now())));
  ui.resetClock.addEventListener("click", () => apply(logic.resetClock(state)));
  ui.undo.addEventListener("click", () => undo(logic.undoAll(history, state)));
  ui.finish.addEventListener("click", onFinish);
  ui.reset.addEventListener("click", startOver);
  ui.searchInput.addEventListener("input", renderResults);
  ui.searchAll.addEventListener("change", renderResults);
  ui.searchClose.addEventListener("click", closeSearch);
  ui.outputClose.addEventListener("click", () => { ui.outputSheet.hidden = true; });
  ui.outputCopy.addEventListener("click", copyOutput);
}

function wireTelegram() {
  if (!tg) {
    return;
  }
  tg.ready();
  tg.expand();
  // A swipe down while reaching for a set must not close the app (Bot API 7.7+).
  if (telegramHas("7.7") && typeof tg.disableVerticalSwipes === "function") {
    tg.disableVerticalSwipes();
  }
  if (!inTelegram) {
    return;
  }
  // Inside Telegram the Finish action is the app's own bottom button (§1).
  ui.finish.hidden = true;
  tg.MainButton.setText("Finish");
  tg.MainButton.onClick(onFinish);
  tg.MainButton.show();
}

async function restoreHistory() {
  try {
    const parsed = JSON.parse(await store.get(`${storeKey}-undo`));
    return Array.isArray(parsed) ? parsed : [];
  } catch (problem) {
    console.warn("the undo history could not be read", problem);
    return [];
  }
}

async function start() {
  wire();
  wireTelegram();
  catalog = await loadCatalog();
  const session = sessionFromUrl();
  storeKey = logic.storageKey(session.r);
  state = await restore(session);
  history = await restoreHistory();
  persist();
  render();
  window.setInterval(tick, 1000);
}

start();
