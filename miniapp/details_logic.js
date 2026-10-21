// The details page's logic (DESIGN_short_messages.md §6): what the button asks for, a proposal
// or a day, and what the page shows of the file. No DOM here, so `node --test` runs it.
import { LOADED, sheetFor, shortDay } from "./calendar_logic.js?v=dev";

// What the page says when it has nothing to show (§6.2, §6.3).
export const COULD_NOT_LOAD =
  "These details could not be loaded. Close this page and tap again in a moment.";
export const REPLACED =
  "This proposal was replaced by a newer one. The newest is further down in the chat.";
export const NOTHING_PLANNED = "Nothing is planned on this day.";
export const NO_BUTTON = "Open this page from a 🔎 Tell me more button in the chat.";

function param(hash, name) {
  return new URLSearchParams((hash || "").replace(/^#/, "")).get(name);
}

export function wantedProposal(hash) {
  // The proposal's number the button carries after `#p=`; null without one.
  const id = Number(param(hash, "p"));
  if (!Number.isInteger(id) || id <= 0) {
    return null;
  }
  return id;
}

export function wantedDay(hash) {
  // The day the button carries after `#d=`, as YYYY-MM-DD; null without one.
  const day = param(hash, "d");
  if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    return null;
  }
  return day;
}

export function monthFileLabel(day) {
  // Word for word `calendar_page.month_label`: the file the day's sheet is in.
  return `calendar/${day.slice(0, 7)}`;
}

export function proposalView(file, wanted) {
  // A file that did not arrive, or that holds an older proposal than the button's, has not
  // caught up with the upload yet; a newer one means this proposal was replaced (§6.2).
  if (!file || file.id < wanted) {
    return { problem: COULD_NOT_LOAD };
  }
  if (file.id > wanted) {
    return { problem: REPLACED };
  }
  return { summary: file.summary || "", cards: file.cards || [], notice: file.notice || "" };
}

export function dayView(file, day) {
  // The day's sheet as the Calendar draws it from the same month file, without the goal
  // the Calendar reads from another file (§6.1).
  if (!file) {
    return { problem: COULD_NOT_LOAD };
  }
  const found = sheetFor({ days: file.days || {}, loaded: { [day.slice(0, 7)]: LOADED },
                           goals: [] }, day);
  if (!found || !found.parts) {
    return { problem: NOTHING_PLANNED };
  }
  return { title: shortDay(day), parts: found.parts };
}
