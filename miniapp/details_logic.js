// The details page's logic (DESIGN_short_messages.md §6): which proposal the button asks for,
// and what the page shows of the proposal's file. No DOM here, so `node --test` runs it.

// What the page says when it has nothing to show (§6.2, §6.3).
export const COULD_NOT_LOAD =
  "These details could not be loaded. Close this page and tap again in a moment.";
export const REPLACED =
  "This proposal was replaced by a newer one. The newest is further down in the chat.";
export const NO_BUTTON = "Open this page from the 🔎 Tell me more button under a proposal.";

export function wantedProposal(hash) {
  // The proposal's number the button carries after `#p=`; null without one.
  const id = Number(new URLSearchParams((hash || "").replace(/^#/, "")).get("p"));
  if (!Number.isInteger(id) || id <= 0) {
    return null;
  }
  return id;
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
