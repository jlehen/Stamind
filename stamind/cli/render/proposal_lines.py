"""A proposal in the companion's words (DESIGN_short_messages.md §3, §6.2): the long text the
terminal, the week planner and an unpublished chat read, the short text a published chat
reads above "Shall I make these changes?", and what the details page shows of it.

Pure functions over a `RevisionProposal`, like `session_lines.py` whose session lines they
are built from."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from stamind.clock import today_str as _today_str
from stamind.cli.render.session_lines import (
    simple_date_word, simple_day_word, simple_session_line, sport_emoji, title_and_length,
)
from stamind.cli.workouts.revisions import (
    rewritten_text_only, wording_group_lines, wording_groups,
)
from stamind.coach.proposals import RevisionProposal
from stamind.text import wrap_text

# The marks before a quoted change: the text that goes, and the text that comes. A terminal
# says it with colour, and the chat has none (DESIGN_workout_revisions.md §9.1).
SIMPLE_GONE_MARK = "🔴 "
SIMPLE_NEW_MARK = "🟢 "

# The change line of a session the proposal removes, written by the code (§3).
REMOVED_LINE = "removed"

# The details page, and the button under a proposal that opens it (§5, §6).
PAGE_URL = "https://jlehen.github.io/Stamind/miniapp/details.html"
PAGE_LABEL = "🔎 Tell me more"


def _is_rest(w: Optional[dict]) -> bool:
    return bool(w) and (w.get('sport_type') or '').lower() == 'rest'


def _simple_was_clause(pw: dict, existing: Optional[dict], today: str) -> str:
    """The parenthetical after a proposed session, saying what it replaces."""
    if not existing:
        return "new"
    if existing['date'] != pw['date']:
        # The same session, on a new day. Said before anything else the clause could
        # say about it, because a session moved unchanged would otherwise read as
        # "new" on one day and vanish from the other.
        day = "today" if existing['date'] == today else simple_date_word(existing['date'])
        return f"moved from {day}"
    if rewritten_text_only(pw, existing):
        return "same session, wording updated"
    if _is_rest(existing):
        return "was a rest day"
    parts = []
    if existing.get('title') != pw.get('title'):
        parts.append(existing['title'])
    if (existing.get('duration_minutes') or 0) != (pw.get('duration_minutes') or 0):
        parts.append(f"{existing.get('duration_minutes') or 0} min")
    return "was " + ", ".join(parts) if parts else "adjusted"


def simple_revision_lines(proposal: RevisionProposal) -> List[str]:
    """The revision as companion prose: one paragraph per touched day, no table and no
    diff signs, so the phone can flow it (DESIGN_bot_simple_frontend.md §6). The
    per-session reason is skipped when it merely repeats the batch reason printed above."""
    today = _today_str()
    entries = []
    # The day that first quoted a given change, so a second gym day rewritten the same way
    # points at it instead of quoting the same passages again.
    first_quoted: Dict[str, str] = {}
    for pair in sorted(proposal.pairs, key=lambda pair: pair.proposal['date']):
        pw, existing = pair.proposal, pair.original
        entry_lines = [_heading(pw, existing, today)]
        why = _own_reason(pw, proposal)
        if why:
            entry_lines.append(why)
        quoted = []
        if rewritten_text_only(pw, existing):
            quoted = _quotes(pw, existing)
        change = "\n\n".join(entry_lines[1:] + quoted)
        if quoted and change in first_quoted:
            same = f"Same change as {first_quoted[change]}."
            entries.append((pw['date'], f"{entry_lines[0]}\n{same}"))
            continue
        first_quoted[change] = simple_day_word(pw['date'], today)
        # A blank line between pairs, so each Was/Now pair reads as one passage.
        entries.append((pw['date'], "\n\n".join(["\n".join(entry_lines)] + quoted)))
    for ew in proposal.removals:
        entries.append((ew['date'], _dropped(ew, today)))
    entries.sort(key=lambda e: e[0])
    return [text for _, text in entries]


def _heading(pw: dict, existing: Optional[dict], today: str) -> str:
    """A changed session's line and what it replaces: '🚴 Sat Oct 10: Long ride — 135 min
    (was Gravel ride)'."""
    day = "Today" if pw['date'] == today else simple_date_word(pw['date'])
    return f"{simple_session_line(pw, lead=day)} ({_simple_was_clause(pw, existing, today)})"


def _own_reason(pw: dict, proposal: RevisionProposal) -> str:
    """The session's own reason, or "" when it only repeats the proposal's."""
    why = (pw.get('modification_reason') or '').strip()
    return "" if why == (proposal.reason or '').strip() else why


def _quotes(pw: dict, existing: Optional[dict]) -> List[str]:
    """The changed passages as "Was" and "Now" pairs, one group each."""
    return [
        "\n".join(wording_group_lines(b, gone=SIMPLE_GONE_MARK, new=SIMPLE_NEW_MARK))
        for b in wording_groups(pw, existing)
    ]


def _dropped(ew: dict, today: str) -> str:
    day = "Today" if ew['date'] == today else simple_date_word(ew['date'])
    return f"🗑 {day}: {ew['title']} — dropped"


def _list_day(date_str: str, today: str) -> str:
    """The day as the week view writes it, 'Fri 09', and 'Today' for today (§3)."""
    if date_str == today:
        return "Today"
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %d")


def simple_change_lines(proposal: RevisionProposal) -> List[str]:
    """One line per session the proposal changes, in date order: its sport, its day and the
    planner's change line, "removed" for a session it removes, and the title and length
    where no change line came back. Every changed session has one (§3)."""
    today = _today_str()
    lines = []
    for pair in proposal.pairs:
        pw = pair.proposal
        change = (pw.get('change') or '').strip() or title_and_length(pw)
        lines.append((pw['date'], f"{sport_emoji(pw.get('sport_type'))} "
                                  f"{_list_day(pw['date'], today)} · {change}"))
    for ew in proposal.removals:
        lines.append((ew['date'], f"{sport_emoji(ew.get('sport_type'))} "
                                  f"{_list_day(ew['date'], today)} · {REMOVED_LINE}"))
    return [line for _, line in sorted(lines, key=lambda entry: entry[0])]


def short_text(proposal: RevisionProposal, opening: Optional[str] = None) -> str:
    """The proposal as the chat reads it above its question: the opening line when there is
    one ("This replaces my earlier proposal."), the reason, the short list, and the
    strength planner's notice (§3)."""
    parts = [opening] if opening else []
    if (proposal.reason or '').strip():
        parts.append(wrap_text(proposal.reason.strip()))
    parts.append("\n".join(simple_change_lines(proposal)))
    if proposal.strength_notice:
        parts.append(wrap_text(proposal.strength_notice))
    return "\n\n".join(parts)


def page_content(proposal: RevisionProposal) -> Dict[str, Any]:
    """What the details page shows of the proposal (§6.2): the summary, then one card per
    changed session in date order. A card is the session's line and what it replaces, its
    own reason, the changed passages when only its text changed, and its whole new text,
    shown open when there is no passage to read first."""
    today = _today_str()
    cards = []
    for pair in proposal.pairs:
        pw, existing = pair.proposal, pair.original
        passages = _quotes(pw, existing) if rewritten_text_only(pw, existing) else []
        cards.append((pw['date'], {
            "line": _heading(pw, existing, today), "why": _own_reason(pw, proposal),
            "passages": passages, "text": (pw.get('description') or '').strip(),
            "open": not passages,
        }))
    for ew in proposal.removals:
        cards.append((ew['date'], {"line": _dropped(ew, today)}))
    return {
        "summary": (proposal.reason or '').strip(),
        "cards": [card for _, card in sorted(cards, key=lambda entry: entry[0])],
        "notice": proposal.strength_notice or "",
    }
