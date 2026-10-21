// The details page's DOM layer (DESIGN_short_messages.md §6): it downloads the proposal's file
// the "🔎 Tell me more" button points at and draws it. Read-only: a page opened from under a
// message cannot send to the bot, so it offers nothing to send. Every text is drawn as plain
// text, because a planner wrote it. "?v=dev" becomes the commit at deploy.
import * as logic from "./details_logic.js?v=dev";
import * as storage from "./storage.js?v=dev";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const ui = {
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

function card(found) {
  // A changed session: its line, its own reason, the passages that changed, and its whole
  // text, folded unless no passage stands before it (§6.2).
  const box = element("section", "card");
  box.append(element("p", "line card-line", found.line));
  if (found.why) {
    box.append(element("p", "line", found.why));
  }
  for (const passage of found.passages || []) {
    box.append(element("p", "line passage", passage));
  }
  if (found.text) {
    const fold = element("details", "card-text");
    fold.open = Boolean(found.open);
    fold.append(element("summary", "", "The whole session"));
    fold.append(element("p", "line", found.text));
    box.append(fold);
  }
  return box;
}

function show(view) {
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

function fail(message) {
  ui.details.hidden = true;
  ui.problem.textContent = message;
  ui.problem.hidden = false;
}

async function start() {
  if (tg) {
    tg.ready();
    tg.expand();
  }
  const wanted = logic.wantedProposal(window.location.hash);
  const files = storage.storageFromHash(window.location.hash);
  if (!wanted || !files) {
    fail(logic.NO_BUTTON);
    return;
  }
  let file = null;
  try {
    file = await storage.fetchFile(files, storage.PROPOSAL);
  } catch (problem) {
    console.warn("the proposal's file could not be had", problem);
  }
  const view = logic.proposalView(file, wanted);
  if (view.problem) {
    fail(view.problem);
    return;
  }
  show(view);
}

start();
