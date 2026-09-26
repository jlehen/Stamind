// The calendar page's DOM layer (DESIGN_calendar_miniapp.md §1, §3): it draws the snapshot
// the bot packed into the address, and hands every question to `calendar_logic.js`.
// "?v=dev" becomes the commit at deploy, like the addresses in calendar.html.
import * as logic from "./calendar_logic.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const ui = {
  title: document.getElementById("title"),
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  goal: document.getElementById("goal"),
  stamp: document.getElementById("stamp"),
  showGrid: document.getElementById("show-grid"),
  showPlan: document.getElementById("show-plan"),
  gridView: document.getElementById("grid-view"),
  planView: document.getElementById("plan-view"),
  grid: document.getElementById("grid"),
  endNote: document.getElementById("end-note"),
  legend: document.getElementById("legend"),
  plan: document.getElementById("plan"),
  problem: document.getElementById("problem"),
  sheet: document.getElementById("day-sheet"),
  sheetTitle: document.getElementById("sheet-title"),
  sheetBody: document.getElementById("sheet-body"),
  sheetClose: document.getElementById("sheet-close"),
};

// The strip colours, numbered along the one list of mesocycles (§4). Past six they repeat.
const STRIPS = 6;
// How far a finger has to travel sideways for a swipe to turn the month.
const SWIPE_PX = 50;

let snapshot = null;
let months = [];
let shown = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function stripClass(index) {
  return index < 0 ? "strip" : `strip meso-${index % STRIPS}`;
}

function renderCell(iso) {
  if (!iso) {
    return element("div", "cell blank");
  }
  const day = snapshot.days[iso];
  const content = logic.cellContent(day);
  const cell = element("button", "cell");
  cell.type = "button";
  const tint = logic.tint(day);
  if (tint) {
    cell.classList.add(tint.kind);
    cell.style.setProperty("--strength", String(tint.strength));
  }
  if (iso === snapshot.today) {
    cell.classList.add("today");
  }
  if (!logic.inWindow(snapshot, iso)) {
    cell.classList.add("outside");
  }
  if (logic.pastTheEnd(snapshot, iso)) {
    cell.classList.add("after-end");
  }
  const top = element("div", "cell-top");
  top.append(element("span", "num", String(logic.parseDay(iso).getDate())));
  if (content.constraint) {
    top.append(element("span", "mark", "◆"));
  }
  if (content.signal) {
    top.append(element("span", "mark", "•"));
  }
  if (logic.goalsOn(snapshot, iso).length) {
    top.append(element("span", "goal-mark", "🎯"));
  }
  cell.append(top);
  const icons = element("div", "icons", content.icons.join(""));
  for (const faded of content.faded) {
    icons.append(element("span", "faded", faded));
  }
  cell.append(icons);
  cell.append(element("div", "label", content.label));
  cell.append(element("div", stripClass(logic.mesoIndex(snapshot, iso))));
  cell.addEventListener("click", () => openSheet(iso));
  return cell;
}

function renderMonth() {
  const month = months[shown];
  ui.title.textContent = logic.monthTitle(month);
  ui.prev.disabled = shown === 0;
  ui.next.disabled = shown === months.length - 1;
  ui.grid.replaceChildren();
  for (const week of logic.monthWeeks(month)) {
    for (const iso of week) {
      ui.grid.append(renderCell(iso));
    }
  }
  ui.endNote.hidden = !logic.endNoteShown(snapshot, month);
  ui.endNote.textContent = logic.END_NOTE;
}

function renderLegend() {
  ui.legend.replaceChildren();
  (snapshot.meso || []).forEach((meso, index) => {
    const row = element("li");
    row.append(element("span", `swatch meso-${index % STRIPS}`));
    row.append(element("span", "", `${meso.n} · ${logic.shortDay(meso.s)} – `
      + logic.shortDay(meso.e)));
    ui.legend.append(row);
  });
}

function renderPlan() {
  // Rows, not links: why the plan is shaped this way stays with "🧭 My plan" (§3.4).
  ui.plan.replaceChildren();
  for (const row of logic.planRows(snapshot)) {
    if (row.kind === "today") {
      ui.plan.append(element("li", "plan-today", "Today"));
      continue;
    }
    const item = element("li", "plan-row");
    if (row.kind === "meso") {
      item.append(element("span", `swatch meso-${row.index % STRIPS}`));
      item.append(element("span", "plan-name", row.name));
      item.append(element("span", "plan-when", row.span));
    } else {
      item.append(element("span", "plan-name", `🎯 ${row.text}`));
    }
    ui.plan.append(item);
  }
}

function openSheet(iso) {
  const found = logic.sheetFor(snapshot, iso);
  if (!found) {
    return;
  }
  ui.sheetTitle.textContent = logic.shortDay(iso);
  ui.sheetBody.replaceChildren();
  if (found.missing) {
    ui.sheetBody.append(element("p", "sheet-note", found.missing));
  }
  for (const [heading, lines] of found.parts || []) {
    ui.sheetBody.append(element("h3", "part", heading));
    for (const line of lines) {
      // The page prints the bot's lines and lets the browser wrap them (§5).
      ui.sheetBody.append(element("p", "line", line));
    }
  }
  // Only a page opened from the keyboard button can send; a browser has no bot (§6).
  if (tg && logic.asksForFullDay(snapshot, iso)) {
    const ask = element("button", "full-day", "💬 Full day in chat");
    ask.type = "button";
    ask.addEventListener("click", () => tg.sendData(logic.fullDayMessage(iso)));
    ui.sheetBody.append(ask);
  }
  ui.sheet.hidden = false;
}

function show(view) {
  const grid = view === "grid";
  ui.gridView.hidden = !grid;
  ui.planView.hidden = grid;
  ui.showGrid.setAttribute("aria-selected", String(grid));
  ui.showPlan.setAttribute("aria-selected", String(!grid));
  ui.prev.hidden = !grid;
  ui.next.hidden = !grid;
  if (!grid) {
    ui.title.textContent = "Plan";
    return;
  }
  renderMonth();
}

function turn(step) {
  const target = shown + step;
  if (target < 0 || target >= months.length) {
    return;
  }
  shown = target;
  renderMonth();
}

function wire() {
  ui.prev.addEventListener("click", () => turn(-1));
  ui.next.addEventListener("click", () => turn(1));
  ui.showGrid.addEventListener("click", () => show("grid"));
  ui.showPlan.addEventListener("click", () => show("plan"));
  ui.sheetClose.addEventListener("click", () => { ui.sheet.hidden = true; });
  ui.sheet.addEventListener("click", (event) => {
    if (event.target === ui.sheet) {
      ui.sheet.hidden = true;
    }
  });
  let startX = null;
  ui.gridView.addEventListener("touchstart", (event) => {
    startX = event.touches[0].clientX;
  }, { passive: true });
  ui.gridView.addEventListener("touchend", (event) => {
    if (startX === null) {
      return;
    }
    const moved = event.changedTouches[0].clientX - startX;
    startX = null;
    if (Math.abs(moved) >= SWIPE_PX) {
      turn(moved < 0 ? 1 : -1);
    }
  });
}

function fail(message) {
  ui.gridView.hidden = true;
  ui.problem.textContent = message;
  ui.problem.hidden = false;
}

async function start() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  wire();
  try {
    snapshot = await logic.snapshotFromHash(window.location.hash);
  } catch (problem) {
    console.warn("the calendar could not be read", problem);
    fail("This calendar could not be read. Send any message to the bot for a fresh button.");
    return;
  }
  if (!snapshot) {
    fail("Open the calendar from the bot's 🗓 Calendar button.");
    return;
  }
  ui.goal.textContent = snapshot.goal || "";
  ui.stamp.textContent = logic.stamp(snapshot.at);
  months = logic.monthsBetween(snapshot.from, snapshot.to);
  shown = logic.monthOf(months, snapshot.today);
  renderLegend();
  renderPlan();
  show("grid");
}

start();
