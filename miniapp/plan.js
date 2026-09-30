// The "Goals & plan" page's DOM layer (DESIGN_calendar_miniapp.md §3.7): it draws the
// snapshot the bot packed into the address, draws again from the plan file when it arrives
// (DESIGN_miniapp_storage.md §7.2), and hands every question to `plan_logic.js`.
// "?v=dev" becomes the commit at deploy, like the addresses in plan.html.
import * as calendar from "./calendar_logic.js?v=dev";
import * as logic from "./plan_logic.js?v=dev";
import * as storage from "./storage.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const ui = {
  stamp: document.getElementById("stamp"),
  plan: document.getElementById("plan"),
  problem: document.getElementById("problem"),
  sheet: document.getElementById("row-sheet"),
  sheetTitle: document.getElementById("sheet-title"),
  sheetBody: document.getElementById("sheet-body"),
  sheetClose: document.getElementById("sheet-close"),
};

// The calendar's strip colours, numbered along the same list of mesocycles (§4).
const STRIPS = 6;

// Whether the plan file arrived, which holds every long text.
let fromFile = false;

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

function openSheet(row) {
  const found = logic.rowSheet(row, fromFile);
  ui.sheetTitle.textContent = found.title;
  ui.sheetBody.replaceChildren();
  for (const line of found.lines) {
    ui.sheetBody.append(element("p", "line", line));
  }
  // Only a page opened from the keyboard button can send; a browser has no bot (§6).
  if (tg && found.why) {
    const ask = element("button", "full-day", "💬 Why, in chat");
    ask.type = "button";
    ask.addEventListener("click", () => tg.sendData(logic.whyMessage(row)));
    ui.sheetBody.append(ask);
  }
  ui.sheet.hidden = false;
}

function rail(row) {
  // The row's stretch of the rail; none outside every mesocycle, where the grey line shows.
  if (!row.rail) {
    return "";
  }
  const done = row.rail.done ? " done" : "";
  return element("span", `rail meso-${row.rail.index % STRIPS}${done}`);
}

function renderPlan(snapshot) {
  ui.plan.replaceChildren();
  for (const row of logic.planRows(snapshot)) {
    if (row.kind === "today") {
      const today = element("li", "plan-today", `Today, ${calendar.shortDay(row.date)}`);
      today.prepend(rail(row));
      ui.plan.append(today);
      continue;
    }
    // A mesocycle is a stretch of the timeline's rail in its strip colour; a goal is a
    // marker on the rail.
    const item = element("li");
    const button = element("button", row.done ? "plan-row done" : "plan-row");
    button.type = "button";
    button.append(rail(row));
    if (row.kind === "meso") {
      button.append(element("span", "plan-name", row.name));
      button.append(element("span", "plan-when", row.span));
    } else {
      button.append(element("span", "node", row.done ? "✅" : "🎯"));
      button.append(element("span", "plan-name goal-name", row.text));
    }
    button.addEventListener("click", () => openSheet(row));
    item.append(button);
    ui.plan.append(item);
  }
}

function wire() {
  ui.sheetClose.addEventListener("click", () => { ui.sheet.hidden = true; });
  ui.sheet.addEventListener("click", (event) => {
    if (event.target === ui.sheet) {
      ui.sheet.hidden = true;
    }
  });
}

function fail(message) {
  ui.plan.hidden = true;
  ui.problem.textContent = message;
  ui.problem.hidden = false;
}

async function start() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  wire();
  let snapshot;
  try {
    snapshot = await calendar.snapshotFromHash(window.location.hash);
  } catch (problem) {
    console.warn("the plan could not be read", problem);
    fail("This page could not be read. Send any message to the bot for a fresh button.");
    return;
  }
  if (!snapshot) {
    fail("Open this page from the bot's 🎯 Goals & plan button.");
    return;
  }
  ui.stamp.textContent = calendar.stamp(snapshot.at);
  renderPlan(snapshot);
  const files = storage.storageFromHash(window.location.hash);
  if (!files) {
    return;
  }
  let file;
  try {
    file = await storage.fetchFile(files, storage.PLAN);
  } catch (problem) {
    console.warn("the plan file could not be had", problem);
    return;
  }
  const at = calendar.later(snapshot.at, file.at);
  fromFile = true;
  ui.stamp.textContent = calendar.stamp(at);
  renderPlan({ ...file, at });
}

start();
