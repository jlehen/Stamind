// The details page's DOM layer (DESIGN_short_messages.md §6): it downloads the file a
// "🔎 Tell me more" button points at, a proposal's or a day's month, and draws it.
// Read-only: a page opened from under a message cannot send to the bot, so it offers nothing
// to send. Every text is drawn as plain text, because a planner wrote it. "?v=dev" becomes
// the commit at deploy.
import * as logic from "./details_logic.js?v=dev";
import * as storage from "./storage.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const ui = {
  title: document.getElementById("title"),
  details: document.getElementById("details"),
  problem: document.getElementById("problem"),
};

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

function fold(label, text, open) {
  const box = element("details", "card-text");
  box.open = Boolean(open);
  box.append(element("summary", "", label));
  box.append(element("p", "line", text));
  return box;
}

function card(found) {
  // A changed session: its line, its own reason, the passages that changed, its whole text,
  // folded unless no passage stands before it, and the session it replaces, folded (§6.2).
  const box = element("section", "card");
  box.append(element("p", "line card-line", found.line));
  if (found.why) {
    box.append(element("p", "line", found.why));
  }
  for (const passage of found.passages || []) {
    box.append(element("p", "line passage", passage));
  }
  if (found.text) {
    box.append(fold("The whole session", found.text, found.open));
  }
  if (found.before) {
    box.append(fold("As planned before", found.before, false));
  }
  return box;
}

function showProposal(view) {
  if (view.summary) {
    ui.details.append(element("p", "line summary", view.summary));
  }
  for (const found of view.cards) {
    ui.details.append(card(found));
  }
  if (view.notice) {
    ui.details.append(element("p", "line sheet-note", view.notice));
  }
}

function showDay(view) {
  // The Calendar's sheet for the day: its headings, and the bot's lines under each (§6.1).
  ui.title.textContent = view.title;
  for (const [heading, lines] of view.parts) {
    ui.details.append(element("h3", "part", heading));
    for (const line of lines) {
      ui.details.append(element("p", "line", line));
    }
  }
}

function fail(message) {
  ui.details.hidden = true;
  ui.problem.textContent = message;
  ui.problem.hidden = false;
}

async function download(files, label) {
  // A file that cannot be had counts as missing; the view says so (§6.3).
  try {
    return await storage.fetchFile(files, label);
  } catch (problem) {
    console.warn(`${label} could not be had`, problem);
    return null;
  }
}

async function start() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  const files = storage.storageFromHash(window.location.hash);
  const proposal = logic.wantedProposal(window.location.hash);
  const day = logic.wantedDay(window.location.hash);
  if (!files || !(proposal || day)) {
    fail(logic.NO_BUTTON);
    return;
  }
  if (proposal) {
    const view = logic.proposalView(await download(files, storage.PROPOSAL), proposal);
    if (view.problem) {
      fail(view.problem);
      return;
    }
    showProposal(view);
    return;
  }
  const view = logic.dayView(await download(files, logic.monthFileLabel(day)), day);
  if (view.problem) {
    fail(view.problem);
    return;
  }
  showDay(view);
}

start();
