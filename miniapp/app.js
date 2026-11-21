// The gym logger's DOM layer (DESIGN_gym_logger.md §1): it draws the session, and hands every
// tap to `logic.js`, which owns the state and the two payloads.
// "?v=dev" becomes the commit at deploy, like the addresses in index.html (§2).
import * as logic from "./logic.js?v=dev";
import { toMarkdown } from "./markdown.js?v=dev";

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
  openedNote: document.getElementById("opened-note"),
  back: document.getElementById("back"),
  edit: document.getElementById("edit"),
  restValue: document.getElementById("rest-value"),
  restLabel: document.getElementById("rest-label"),
  rest: document.getElementById("rest"),
  startClock: document.getElementById("start-clock"),
  undo: document.getElementById("undo"),
  order: document.getElementById("order"),
  orderSheet: document.getElementById("order-sheet"),
  orderRows: document.getElementById("order-rows"),
  orderClose: document.getElementById("order-close"),
  orderTrade: document.getElementById("order-trade"),
  orderMove: document.getElementById("order-move"),
  orderHint: document.getElementById("order-hint"),
  orderEnd: document.getElementById("order-end"),
  resetClock: document.getElementById("reset-clock"),
  resumeClock: document.getElementById("resume-clock"),
  cards: document.getElementById("cards"),
  sessionNote: document.getElementById("session-note"),
  addExercise: document.getElementById("add-exercise"),
  exportMd: document.getElementById("export-md"),
  finish: document.getElementById("finish"),
  sent: document.getElementById("sent"),
  reset: document.getElementById("reset"),
  searchSheet: document.getElementById("search-sheet"),
  searchTitle: document.getElementById("search-title"),
  searchInput: document.getElementById("search-input"),
  searchAll: document.getElementById("search-all"),
  searchAllRow: document.getElementById("search-all-row"),
  searchFilter: document.getElementById("search-filter"),
  searchResults: document.getElementById("search-results"),
  searchClose: document.getElementById("search-close"),
  outputSheet: document.getElementById("output-sheet"),
  outputTitle: document.getElementById("output-title"),
  outputHint: document.getElementById("output-hint"),
  outputNote: document.getElementById("output-note"),
  outputText: document.getElementById("output-text"),
  outputCopy: document.getElementById("output-copy"),
  outputRetry: document.getElementById("output-retry"),
  outputClose: document.getElementById("output-close"),
};

// The 4,096-byte cap on one `sendData` message, in the digits the athlete reads (§4).
const LIMIT = logic.MAX_LOG_BYTES.toLocaleString("en-US");

// How long the page waits for Telegram to take the log and close the app, and what it says
// when that does not happen. A slow phone can still be closing, so the words allow for a log
// that did arrive, and Retry is safe because the bot replaces the earlier log (§1).
const SEND_WATCHDOG_MS = 2000;
const SEND_FAILED = "Telegram has not closed the page, so the log may not have reached the bot. "
  + "Tap Retry. Sending twice is safe: the bot keeps the last one.";

let catalog = [];
// The exercises whose photos are open. Not saved: they close when the page reloads.
const photosOpen = new Set();
let state = null;
// What Undo takes back, oldest first (`logic.record`). Saved beside the state.
let history = [];
let storeKey = "";
// The log the calendar opened the page on, or null in the gym (§8). Such a page shows what the
// bot holds, so it reads nothing from the phone and saves nothing on it.
let opened = null;
// Whether the cards are read-only: an opened log is, until Edit.
let locked = false;
const OPENED_LOCKED = "This is the log the bot holds for this session. Tap Edit to change it.";
const OPENED_EDITING = "Send again replaces the log the bot holds. A change you do not send is "
  + "lost when the page closes.";
// What the search sheet is for: "swap" (the card's Replace) or "insert" the card at
// `searchIndex`, or "add" one; "replace" the movement `searchPart` of that card, or "chain" a
// pick after it.
let searchMode = "add";
let searchIndex = null;
let searchPart = null;
let replacePattern = null;
// The chip whose three buttons show, `{ card, part }`, or null. Not saved.
let openChip = null;
// The id of the card whose ✕ waits for its second tap, or null, and the timer that lets it go
// (§1). Not saved.
let armed = null;
let armedTimer = 0;
const ARMED_MS = 3000;
// In the Order sheet: whether two taps move the first card above the second ("Move above") or
// make the two trade places, the id of the card waiting for its second tap, or null, and the
// ids of the cards the last tap moved. Not saved.
let orderMoves = false;
let orderPicked = null;
let orderSwapped = [];

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
  if (opened) {
    return;
  }
  store.set(storeKey, JSON.stringify(state));
  store.set(`${storeKey}-undo`, JSON.stringify(history));
}

// ---------------------------------------------------------------------------------------
// Applying a change. `apply` redraws, `applyQuiet` does not, because a redraw triggered by a
// field losing focus would replace the button the tap was heading for. Both record the change
// for Undo, under the card it was made on (`card`, its id) or under the page (null). Both, and
// an undo, close the open chip box: its place in the card may now hold another movement. Every
// change lets an armed ✕ go.
// ---------------------------------------------------------------------------------------

function remember(after, card) {
  if (after !== state) {
    history = logic.record(history, state, card);
  }
  state = after;
  openChip = null;
  disarm();
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

// Undo neither takes back a Finish nor brings it back (§1), so Finish and Resume go around the
// history.
function applyUnrecorded(after) {
  state = after;
  disarm();
  persist();
  render();
}

function undo(result) {
  if (!result) {
    return;
  }
  state = result.state;
  history = result.history;
  openChip = null;
  disarm();
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
  renderOrder();
  renderOpened();
  tick();
}

// A log opened from the calendar (§8): its own two buttons and its note, the cards out of reach
// while it is locked, and Telegram's bottom button only once Edit unlocked it.
function renderOpened() {
  if (!opened) {
    return;
  }
  document.body.classList.toggle("locked", locked);
  ui.cards.inert = locked;
  ui.sessionNote.disabled = locked;
  ui.edit.textContent = locked ? "✏️ Edit" : "🔒 Lock";
  ui.openedNote.textContent = locked ? OPENED_LOCKED : OPENED_EDITING;
  ui.sent.hidden = true;
  syncMainButton();
}

// Telegram's bottom button is not part of the page, so a sheet does not cover it: it hides
// while a sheet is up, and on an opened log while it is locked (§1, §8).
function syncMainButton() {
  if (!inTelegram) {
    return;
  }
  const sheetUp = !ui.searchSheet.hidden || !ui.outputSheet.hidden || !ui.orderSheet.hidden;
  if (sheetUp || (opened && locked)) {
    tg.MainButton.hide();
  } else {
    tg.MainButton.show();
  }
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
  const words = logic.wordsOf(catalog, exercise.n);
  name.append(cardTitle(exercise, xi));
  name.append(el("div", "card-pres",
    logic.prescriptionLine(exercise, logic.perSideOf(catalog, exercise.n))));
  head.append(name);
  const photos = logic.photosOf(catalog, exercise.n);
  head.append(cardMoves(exercise, xi, words, photos.length > 0));
  card.append(head);

  if (photosOpen.has(exercise.n)) {
    const strip = el("div", "photos");
    for (const address of photos) {
      const photo = el("img");
      photo.src = address;
      photo.alt = `${words}, photo`;
      photo.loading = "lazy";
      strip.append(photo);
    }
    card.append(strip);
  }

  // The main rows are numbered from 1; a warm-up row reads "W" (§1).
  let number = 0;
  exercise.sets.forEach((set, si) => {
    if (!set.w) {
      number += 1;
    }
    card.append(setRow(exercise, xi, set, si, number));
  });

  const tools = el("div", "tools");
  const undoCard = button("↶", "pill undo", () => undo(logic.undoCard(history, state, id)));
  undoCard.disabled = !logic.canUndoCard(history, id);
  undoCard.setAttribute("aria-label", `Undo the last change to ${words}`);
  tools.append(undoCard);
  tools.append(...setButtons(xi, id));
  tools.append(button("⤵ Insert", "pill", () => openSearch("insert", xi)));
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

// The buttons that act on the whole card, beside its name: ↑ ↓ over ⇆ ✕, and 📷 in a column of
// its own when the exercise has photos (§1). Their places are `.moves` grid areas (style.css).
function cardMoves(exercise, xi, words, hasPhotos) {
  const moves = el("div", "moves");
  if (hasPhotos) {
    moves.classList.add("with-photos");
    const shown = photosOpen.has(exercise.n);
    const verb = shown ? "Hide" : "Show";
    const pic = iconButton("📷", "pic", `${verb} the photos of ${words}`,
                           () => togglePhotos(exercise.n));
    pic.setAttribute("aria-pressed", String(shown));
    moves.append(pic);
  }
  moves.append(
    iconButton("↑", "up", `Move ${words} up`, () => apply(logic.moveExercise(state, xi, -1))),
    iconButton("↓", "down", `Move ${words} down`,
               () => apply(logic.moveExercise(state, xi, 1))),
    iconButton("⇆", "replace", `Replace ${words}`, () => openSearch("swap", xi)),
    delButton(xi, exercise.id, words),
  );
  return moves;
}

function iconButton(icon, kind, label, onClick) {
  const node = button(icon, `move ${kind}`, onClick);
  node.setAttribute("aria-label", label);
  return node;
}

// ✕ takes two taps: the first arms it, the second deletes the card, one step for the header's
// Undo (§1).
function delButton(xi, id, words) {
  const del = button("✕", "move del", () => {
    if (armed !== id) {
      arm(id, del);
      return;
    }
    apply(logic.removeExercise(state, xi));
  });
  del.dataset.words = words;
  drawDel(del, armed === id);
  return del;
}

// Arming and letting go change the button in place: a redraw would replace the number field the
// athlete may be typing in.
function arm(id, del) {
  disarm();
  armed = id;
  drawDel(del, true);
  armedTimer = window.setTimeout(disarm, ARMED_MS);
}

function disarm() {
  window.clearTimeout(armedTimer);
  if (armed === null) {
    return;
  }
  armed = null;
  const del = ui.cards.querySelector(".del.armed");
  if (del) {
    drawDel(del, false);
  }
}

function drawDel(del, on) {
  del.classList.toggle("armed", on);
  const label = on ? "Tap again to delete" : "Delete";
  del.setAttribute("aria-label", `${label} ${del.dataset.words}`);
}

// A touch anywhere but on the armed ✕ lets it go. `pointerdown`, because iOS fires no click on
// a tap that lands on plain text, so the document would not hear it.
function letGoOfDel(event) {
  if (event.target.closest(".del.armed")) {
    return;
  }
  disarm();
}

// The card's set buttons, two split pills: a main row and a warm-up row, each taken away by
// the pill's left half and added by its right half (§1).
function setButtons(xi, id) {
  const act = (change) => () => apply(change(state, xi), id);
  return [
    splitPill("Set", "split", ["Remove the last main set", act(logic.removeSet)],
              ["Add a main set", act(logic.addSet)]),
    splitPill("W Set", "split warmup", ["Remove the last warm-up set", act(logic.removeWarmup)],
              ["Add a warm-up set", act(logic.addWarmup)]),
  ];
}

// One cell that looks like a pill: two buttons, "−" and "+", under a word that lets taps through.
function splitPill(word, className, [lessLabel, onLess], [moreLabel, onMore]) {
  const cell = el("div", className);
  const less = button("−", "half less", onLess);
  less.setAttribute("aria-label", lessLabel);
  const more = button("+", "half more", onMore);
  more.setAttribute("aria-label", moreLabel);
  cell.append(less, more, el("span", "split-word", word));
  return cell;
}

// Every title is chips, one per movement, a chain's opened by ⛓. A tap on a chip boxes it with
// the three buttons that act on that movement (DESIGN_strength_combos.md §6).
function cardTitle(exercise, xi) {
  const chips = logic.chipsOf(catalog, exercise.n);
  const title = el("div", "card-title");
  if (chips.length > 1) {
    title.append(el("span", "chain-mark", "⛓"));
  }
  chips.forEach((chip, part) => {
    if (part) {
      title.append(el("span", "chain-arrow", "→"));
    }
    title.append(movement(exercise, xi, chip, part, chips.length));
  });
  return title;
}

function movement(exercise, xi, chip, part, count) {
  const open = Boolean(openChip) && openChip.card === exercise.id && openChip.part === part;
  const box = el("div", open ? "part open" : "part");
  const name = button(chip, "chip", () => {
    openChip = open ? null : { card: exercise.id, part };
    render();
  });
  name.setAttribute("aria-expanded", String(open));
  box.append(name);
  if (!open) {
    return box;
  }
  const menu = el("div", "part-menu");
  menu.append(button("⇆ Replace", "pill", () => openSearch("replace", xi, part)));
  menu.append(button("✕ Remove", "pill danger", () => {
    // The last movement of a card goes the way the card's ✕ takes the card.
    if (count === 1) {
      apply(logic.removeExercise(state, xi));
      return;
    }
    editChain(xi, logic.removePart(exercise.n, part));
  }));
  menu.append(button("⛓ Chain with", "pill", () => openSearch("chain", xi, part)));
  box.append(menu);
  return box;
}

// A chip's edit swaps in the card's new key: the sets stay, the card's ↶ takes it back.
function editChain(xi, key) {
  apply(logic.swapExercise(state, xi, key), state.x[xi].id);
}

function togglePhotos(name) {
  if (photosOpen.has(name)) {
    photosOpen.delete(name);
  } else {
    photosOpen.add(name);
  }
  render();
}

// `number` is the row's place among the card's main rows.
function setRow(exercise, xi, set, si, number) {
  const id = exercise.id;
  const row = el("div", set.done ? "set done" : "set");
  row.classList.toggle("warmup", set.w);
  row.append(setMark(exercise, xi, set, si, number));

  const perSide = logic.perSideOf(catalog, exercise.n);
  row.append(stepper({
    value: String(set.reps),
    // A set of an exercise done one side at a time is both sides, and its reps are per side.
    unit: perSide ? logic.SIDE_MARK : "reps",
    label: perSide ? "reps per side" : "reps",
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
  const which = set.w ? "Warm-up set" : `Set ${number}`;
  check.setAttribute("aria-label", set.done ? `${which} done` : `Mark ${which.toLowerCase()} done`);
  row.append(check);
  return row;
}

// The row's mark, "W" or its number, is the button that switches it between warm-up and main.
// Its look, and the warm-up row's, lives here and in `.mark` and `.set.warmup` (style.css).
function setMark(exercise, xi, set, si, number) {
  const flip = () => apply(logic.toggleWarmup(state, xi, si), exercise.id);
  if (set.w) {
    const mark = button("W", "mark warmup", flip);
    mark.setAttribute("aria-label", "Warm-up set, tap to make it a main set");
    return mark;
  }
  const mark = button(String(number), "mark", flip);
  mark.setAttribute("aria-label", `Set ${number}, tap to make it a warm-up set`);
  return mark;
}

function stepper(spec) {
  const box = el("div", "stepper");
  box.append(button("−", "step", spec.onMinus));
  const field = el("input", "num");
  field.type = "text";
  field.inputMode = "decimal";
  field.value = spec.value;
  field.setAttribute("aria-label", spec.label || spec.unit);
  field.addEventListener("focus", () => field.select());
  field.addEventListener("change", () => spec.onType(field.value, field));
  // The unit under the number, so reps and kilograms cannot be told apart by position only.
  const middle = el("label", "num-box");
  middle.append(field);
  middle.append(el("span", "unit", spec.unit));
  box.append(middle);
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
  // An opened log keeps its day and its clock times (§8).
  ui.resetClock.hidden = !started || Boolean(opened) || Boolean(state.finishedAt);
  ui.resumeClock.hidden = !started || Boolean(opened) || !state.finishedAt;
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
// The Order sheet: one line per card, so the whole session is in reach without scrolling. A
// tap picks a line, and a tap on another makes the two trade places or, under "Move above",
// puts the first above the second; one Undo step each (§1).
// ---------------------------------------------------------------------------------------

// The sheet always opens on "Trade places".
function showOrder(shown) {
  ui.orderSheet.hidden = !shown;
  syncMainButton();
  setOrderMode(false);
}

function setOrderMode(moves) {
  orderMoves = moves;
  orderPicked = null;
  orderSwapped = [];
  renderOrder();
}

function renderOrder() {
  if (ui.orderSheet.hidden) {
    return;
  }
  ui.orderTrade.setAttribute("aria-pressed", String(!orderMoves));
  ui.orderMove.setAttribute("aria-pressed", String(orderMoves));
  ui.orderHint.textContent = orderMoves
    ? "Tap an exercise, then the line it goes above."
    : "Tap two exercises: they trade places.";
  ui.orderEnd.hidden = !orderMoves || orderPicked === null;
  ui.orderRows.replaceChildren(...state.x.map(orderRow));
}

function orderRow(exercise, xi) {
  const row = button("", "order-row", () => onOrderTap(xi));
  if (exercise.id === orderPicked) {
    row.classList.add("picked");
  }
  if (orderSwapped.includes(exercise.id)) {
    row.classList.add("swapped");
  }
  row.setAttribute("aria-pressed", String(exercise.id === orderPicked));
  row.append(el("span", "order-name", logic.wordsOf(catalog, exercise.n)));
  // The card's heaviest load, so a warm-up row does not stand for the card.
  const loads = exercise.sets.map((set) => set.kg).filter((kg) => kg !== null);
  const load = loads.length ? `${logic.formatKg(Math.max(...loads))} kg` : logic.formatKg(null);
  const ticked = exercise.sets.every((set) => set.done);
  row.append(el("span", "order-load", ticked ? `✓ ${load}` : load));
  return row;
}

function onOrderTap(xi) {
  const id = state.x[xi].id;
  const from = state.x.findIndex((exercise) => exercise.id === orderPicked);
  if (from < 0 || from === xi) {
    // The first tap picks the line, and a second tap on it lets it go.
    orderPicked = from === xi ? null : id;
    orderSwapped = [];
    renderOrder();
    return;
  }
  if (orderMoves) {
    placePicked(from, xi);
    return;
  }
  orderSwapped = [orderPicked, id];
  orderPicked = null;
  apply(logic.swapExercises(state, from, xi));
}

// "Move above": the picked card goes right above the card at `before`, or to the end.
function placePicked(from, before) {
  orderSwapped = [orderPicked];
  orderPicked = null;
  apply(logic.moveExerciseAbove(state, from, before));
}

function onOrderEnd() {
  const from = state.x.findIndex((exercise) => exercise.id === orderPicked);
  if (from >= 0) {
    placePicked(from, state.x.length);
  }
}

// ---------------------------------------------------------------------------------------
// The exercise search: the card's Replace keeps the card's movement pattern as its filter, an
// added or inserted exercise searches everything (§1). A chip's Replace keeps its movement's
// pattern, its Chain with searches everything (DESIGN_strength_combos.md §6).
// ---------------------------------------------------------------------------------------

function openSearch(mode, xi = null, part = null) {
  searchMode = mode;
  searchIndex = xi;
  searchPart = part;
  replacePattern = searchPattern(mode, xi, part);
  ui.searchTitle.textContent = searchTitle(mode, xi, part);
  ui.searchAllRow.hidden = !replacePattern;
  ui.searchAll.checked = !replacePattern;
  ui.searchInput.value = "";
  ui.searchSheet.hidden = false;
  syncMainButton();
  renderResults();
  ui.searchInput.focus();
}

function searchPattern(mode, xi, part) {
  if (mode === "swap") {
    return logic.patternOf(catalog, state.x[xi].n);
  }
  if (mode === "replace") {
    return logic.patternOf(catalog, logic.partsOf(state.x[xi].n)[part]);
  }
  return null;
}

function searchTitle(mode, xi, part) {
  if (mode === "swap") {
    return `Replace ${logic.wordsOf(catalog, state.x[xi].n)}`;
  }
  if (mode === "insert") {
    return `Insert after ${logic.wordsOf(catalog, state.x[xi].n)}`;
  }
  if (mode === "replace") {
    return `Replace ${logic.chipsOf(catalog, state.x[xi].n)[part]}`;
  }
  if (mode === "chain") {
    return `Chain with ${logic.chipsOf(catalog, state.x[xi].n)[part]}`;
  }
  return "Add an exercise";
}

function closeSearch() {
  ui.searchSheet.hidden = true;
  syncMainButton();
}

function renderResults() {
  const pattern = ui.searchAll.checked ? null : replacePattern;
  ui.searchFilter.textContent = pattern ? `— only ${pattern.replace(/_/g, " ")}` : "";
  const hits = logic.searchExercises(catalog, ui.searchInput.value, pattern);
  if (!hits.length) {
    ui.searchResults.replaceChildren(el("p", "empty", "Type a few letters of the exercise."));
    return;
  }
  ui.searchResults.replaceChildren(...hits.map((row) => {
    const hit = button("", "result", () => choose(row));
    hit.append(el("span", "result-name", logic.shown(row.w)));
    const also = row.a ? `also ${row.a}` : "";
    const kind = [also, row.p.replace(/_/g, " "), row.g].filter(Boolean).join(" · ");
    hit.append(el("span", "result-kind", kind));
    return hit;
  }));
}

function choose(row) {
  closeSearch();
  if (searchMode === "swap") {
    apply(logic.swapExercise(state, searchIndex, row.k), state.x[searchIndex].id);
    return;
  }
  if (searchMode === "insert") {
    apply(logic.addExercise(state, row.k, row.b, searchIndex + 1));
    return;
  }
  if (searchMode === "replace") {
    editChain(searchIndex, logic.replacePart(state.x[searchIndex].n, searchPart, row.k));
    return;
  }
  if (searchMode === "chain") {
    editChain(searchIndex, logic.chainAfter(state.x[searchIndex].n, searchPart, row.k));
    return;
  }
  apply(logic.addExercise(state, row.k, row.b));
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
      // A taken message closes the app, so a page still here after the wait may mean the log
      // never left, and the athlete gets Retry and the same sheet to copy from.
      window.setTimeout(() => showOutput(result, SEND_FAILED), SEND_WATCHDOG_MS);
      return;
    } catch (problem) {
      console.warn("sendData failed", problem);
    }
  }
  showOutput(result);
}

function showOutput(result, hint) {
  showSheet("Your log", result.text, `${result.bytes} bytes of the ${LIMIT} Telegram allows. `
    + "You can also copy it and paste it in the chat with the bot.", hint);
}

function showSheet(title, text, note, hint) {
  ui.outputTitle.textContent = title;
  ui.outputHint.textContent = hint || "";
  ui.outputHint.hidden = !hint;
  // The hint is the failed send's, so Retry comes with it (§1).
  ui.outputRetry.hidden = !hint;
  ui.outputNote.textContent = note;
  ui.outputText.value = text;
  ui.outputCopy.textContent = "Copy";
  ui.outputSheet.hidden = false;
  syncMainButton();
}

// The Markdown goes straight to the clipboard; a phone that refuses it gets the sheet (§1).
function exportMarkdown() {
  const text = toMarkdown(state, Date.now(), catalog);
  const refused = () => showSheet("Markdown", text, "Select the text and copy it.");
  if (!navigator.clipboard || !navigator.clipboard.writeText) {
    refused();
    return;
  }
  navigator.clipboard.writeText(text).then(() => {
    ui.exportMd.textContent = "Copied ✓";
    window.setTimeout(() => { ui.exportMd.textContent = "Export to Markdown"; }, 2000);
  }, refused);
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

function logFromUrl() {
  try {
    return logic.logFromHash(window.location.hash);
  } catch (problem) {
    console.warn("the log in the URL could not be read", problem);
    return null;
  }
}

// The page on a past log (§8): Back and Edit in the header, and no Start over.
function showOpened() {
  locked = true;
  ui.back.hidden = false;
  ui.edit.hidden = false;
  ui.openedNote.hidden = false;
  ui.reset.hidden = true;
}

async function loadCatalog() {
  try {
    // "?v=dev" becomes the commit at deploy, like the imports above (DESIGN_exercise_table.md §8).
    const answer = await fetch("./exercises.json?v=dev");
    return await answer.json();
  } catch (problem) {
    console.warn("exercises.json could not be read", problem);
    return [];
  }
}

// The state saved for this day when it wins over the URL, so a reopened app carries on (§1);
// null when the page starts from the session.
async function restore(session) {
  const saved = await store.get(storeKey);
  if (!saved) {
    return null;
  }
  try {
    const parsed = JSON.parse(saved);
    if (parsed && parsed.v === logic.STATE_VERSION && Array.isArray(parsed.x)
        && logic.keepsSaved(parsed, session)) {
      return parsed;
    }
  } catch (problem) {
    console.warn("the saved session could not be read", problem);
  }
  return null;
}

function wire() {
  document.addEventListener("pointerdown", letGoOfDel);
  ui.sessionNote.addEventListener("change",
    () => applyQuiet(logic.setSessionNote(state, ui.sessionNote.value)));
  ui.addExercise.addEventListener("click", () => openSearch("add"));
  ui.exportMd.addEventListener("click", exportMarkdown);
  ui.startClock.addEventListener("click", () => apply(logic.startClock(state, Date.now())));
  ui.resetClock.addEventListener("click", () => apply(logic.resetClock(state)));
  ui.resumeClock.addEventListener("click", () => applyUnrecorded(logic.resumeClock(state)));
  ui.undo.addEventListener("click", () => undo(logic.undoAll(history, state)));
  ui.finish.addEventListener("click", onFinish);
  ui.reset.addEventListener("click", startOver);
  ui.back.addEventListener("click", backToCalendar);
  ui.edit.addEventListener("click", () => {
    locked = !locked;
    render();
  });
  ui.order.addEventListener("click", () => showOrder(true));
  ui.orderClose.addEventListener("click", () => showOrder(false));
  ui.orderTrade.addEventListener("click", () => setOrderMode(false));
  ui.orderMove.addEventListener("click", () => setOrderMode(true));
  ui.orderEnd.addEventListener("click", onOrderEnd);
  ui.searchInput.addEventListener("input", renderResults);
  ui.searchAll.addEventListener("change", renderResults);
  ui.searchClose.addEventListener("click", closeSearch);
  ui.outputClose.addEventListener("click", () => {
    ui.outputSheet.hidden = true;
    syncMainButton();
  });
  ui.outputCopy.addEventListener("click", copyOutput);
  ui.outputRetry.addEventListener("click", () => {
    ui.outputSheet.hidden = true;
    syncMainButton();
    onFinish();
  });
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
  // An opened log gets the button once Edit unlocked it (§8).
  if (!opened) {
    tg.MainButton.show();
  }
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

// Back to the calendar from a past log (§8).
function backToCalendar() {
  // The bottom button is Telegram's own, so it would stay up over the calendar.
  if (inTelegram) {
    tg.MainButton.hide();
  }
  window.history.back();
}

// What a session of another version opens on: one line, no session drawn and nothing saved on
// the phone (DESIGN_exercise_table.md §8). A past log opened from the calendar gets its own
// line and the Back button, since the athlete came from a day's sheet and not from a button.
function showOutOfDate() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  const line = el("p", "head-notes", logic.outOfDateLine(opened));
  if (!opened) {
    document.body.replaceChildren(line);
    return;
  }
  const actions = el("div", "head-actions");
  ui.back.hidden = false;
  ui.back.addEventListener("click", backToCalendar);
  actions.append(ui.back);
  document.body.replaceChildren(line, actions);
}

async function start() {
  const session = sessionFromUrl();
  // Read before the version check, which says other words for a past log, and before
  // `wireTelegram`, which leaves the bottom button out for one.
  opened = logFromUrl();
  if (!logic.isCurrent(session)) {
    showOutOfDate();
    return;
  }
  wire();
  wireTelegram();
  const catalogLoad = loadCatalog();
  if (opened) {
    state = logic.stateFromLog(session, opened);
    showOpened();
  } else {
    storeKey = logic.storageKey(session.d);
    const saved = await restore(session);
    state = saved || logic.newState(session);
    // A fresh state takes no undo history: what is saved undid another revision's cards.
    history = saved ? await restoreHistory() : [];
    persist();
  }
  // The clock is back as soon as the phone answers, not after the download: a reopened page
  // never shows it stopped (§1). The cards wait for the exercises' words.
  tick();
  window.setInterval(tick, 1000);
  catalog = await catalogLoad;
  render();
}

start();
