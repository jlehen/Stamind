// The gym logger's DOM layer (DESIGN_gym_logger.md §1): it draws the session, and hands every
// tap to `logic.js`, which owns the state and the two payloads.
import * as logic from "./logic.js";

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
  cards: document.getElementById("cards"),
  sessionNote: document.getElementById("session-note"),
  addExercise: document.getElementById("add-exercise"),
  finish: document.getElementById("finish"),
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
let state = null;
let storeKey = "";
let swapIndex = null;
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
}

// ---------------------------------------------------------------------------------------
// Applying a change. `apply` redraws, `applyQuiet` does not, because a redraw triggered by a
// field losing focus would replace the button the tap was heading for.
// ---------------------------------------------------------------------------------------

function apply(after) {
  state = after;
  persist();
  render();
}

function applyQuiet(after) {
  state = after;
  persist();
  tick();
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
  tick();
}

function exerciseCard(exercise, xi) {
  const card = el("section", "card");

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

  exercise.sets.forEach((set, si) => card.append(setRow(exercise, xi, set, si)));

  const tools = el("div", "tools");
  tools.append(button("+ Set", "pill", () => apply(logic.addSet(state, xi))));
  tools.append(button("− Set", "pill", () => apply(logic.removeSet(state, xi))));
  tools.append(button("⇄ Swap", "pill", () => openSearch(xi)));
  tools.append(button("✕ Remove", "pill danger", () => apply(logic.removeExercise(state, xi))));
  card.append(tools);

  const note = el("input", "note");
  note.type = "text";
  note.placeholder = "Note on this exercise";
  note.value = exercise.note || "";
  note.addEventListener("change", () => applyQuiet(logic.setExerciseNote(state, xi, note.value)));
  card.append(note);
  return card;
}

function setRow(exercise, xi, set, si) {
  const row = el("div", set.done ? "set done" : "set");
  row.append(el("div", "set-index", String(si + 1)));

  row.append(stepper({
    value: String(set.reps),
    unit: "reps",
    onMinus: () => apply(logic.bumpReps(state, xi, si, -logic.REP_STEP)),
    onPlus: () => apply(logic.bumpReps(state, xi, si, logic.REP_STEP)),
    onType: (text, field) => {
      applyQuiet(logic.setReps(state, xi, si, parseFloat(text)));
      field.value = String(state.x[xi].sets[si].reps);
    },
  }));

  row.append(stepper({
    value: logic.formatKg(set.kg),
    unit: "kg",
    onMinus: () => apply(logic.bumpKg(state, xi, si, -logic.KG_STEP)),
    onPlus: () => apply(logic.bumpKg(state, xi, si, logic.KG_STEP)),
    onType: (text, field) => {
      const typed = text.trim() === "" || /^bw$/i.test(text.trim()) ? null : parseFloat(text);
      applyQuiet(logic.setKg(state, xi, si, typed));
      field.value = logic.formatKg(state.x[xi].sets[si].kg);
    },
  }));

  const check = button("✓", "tick", () => apply(logic.toggleDone(state, xi, si, secondsNow())));
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

function secondsNow() {
  return (Date.now() - state.startedAt) / 1000;
}

function tick() {
  const done = logic.doneSetCount(state);
  ui.tally.textContent = done === 1 ? "· 1 set done" : `· ${done} sets done`;
  const last = logic.lastSetSeconds(state);
  ui.restLabel.textContent = done ? "since last set" : "since start";
  ui.restValue.textContent = logic.formatMMSS(secondsNow() - last);
}

// ---------------------------------------------------------------------------------------
// The exercise search: a swap keeps the card's movement pattern as its filter, an added
// exercise searches everything (§1).
// ---------------------------------------------------------------------------------------

function openSearch(xi) {
  swapIndex = xi;
  swapPattern = xi === null ? null : logic.patternOf(catalog, state.x[xi].n);
  ui.searchTitle.textContent = xi === null ? "Add an exercise" : "Swap exercise";
  ui.searchAllRow.hidden = xi === null || !swapPattern;
  ui.searchAll.checked = !swapPattern;
  ui.searchInput.value = "";
  ui.searchSheet.hidden = false;
  renderResults();
  ui.searchInput.focus();
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
  if (swapIndex === null) {
    apply(logic.addExercise(state, row.n, row.e));
    return;
  }
  apply(logic.swapExercise(state, swapIndex, row.n));
}

// ---------------------------------------------------------------------------------------
// Finishing: build the log, check it fits, send it or show it (§4).
// ---------------------------------------------------------------------------------------

function onFinish() {
  const result = logic.finish(state, Date.now());
  if (!result.log.x.length) {
    say("No set is ticked yet, so there is nothing to send.");
    return;
  }
  if (!result.fits) {
    say(`This log is ${result.bytes} bytes and Telegram accepts ${LIMIT}. `
        + "Shorten the notes, or remove an exercise you did not do.");
    return;
  }
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
  ask("Throw away everything logged here and start from the written session?", () => {
    store.remove(storeKey);
    apply(logic.newState(sessionFromUrl(), Date.now()));
  });
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
    return logic.newState(session, Date.now());
  }
  try {
    const parsed = JSON.parse(saved);
    // A saved state for this revision wins over the URL, so a reopened app carries on (§1).
    if (parsed && parsed.v === 1 && parsed.r === session.r && Array.isArray(parsed.x)) {
      return parsed;
    }
  } catch (problem) {
    console.warn("the saved session could not be read", problem);
  }
  return logic.newState(session, Date.now());
}

function wire() {
  ui.sessionNote.addEventListener("change",
    () => applyQuiet(logic.setSessionNote(state, ui.sessionNote.value)));
  ui.addExercise.addEventListener("click", () => openSearch(null));
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

async function start() {
  wire();
  wireTelegram();
  catalog = await loadCatalog();
  const session = sessionFromUrl();
  storeKey = logic.storageKey(session.r);
  state = await restore(session);
  persist();
  render();
  window.setInterval(tick, 1000);
}

start();
