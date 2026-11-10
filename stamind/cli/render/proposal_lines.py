"""A proposal in the companion's words (DESIGN_short_messages.md §3, §6.2): the long text the
terminal, the week planner and an unpublished chat read, the short text a published chat
reads above "Shall I make these changes?", and what the details page shows of it.

Pure functions over a `RevisionProposal`, like `session_lines.py` whose session lines they
are built from."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from stamind.clock import shift, today_str as _today_str
from stamind.cli.render.session_lines import (
    simple_date_word, simple_day_word, simple_session_line, sport_emoji,
)
from stamind.cli.workouts.revisions import (
    CAME, GONE, rewritten_text_only, wording_group_lines, wording_group_sides, wording_groups,
)
from stamind.coach.proposals import RevisionProposal
from stamind.sports import canonical_sport
from stamind.text import wrap_text

# The marks before a quoted change: the text that goes, and the text that comes. A terminal
# says it with colour, and the chat has none (DESIGN_workout_revisions.md §9.1).
SIMPLE_GONE_MARK = "🔴 "
SIMPLE_NEW_MARK = "🟢 "

# The short list's words for a session the change leaves alone, and for a day it empties (§3).
UNCHANGED = "(unchanged)"
NOTHING_PLANNED = "nothing planned"
# The lines under a day in the short list, set under its sessions (§3).
REPLACED_INDENT = "    "
# The days between the changed ones are listed only when the changed days fit in this many
# days (§3, D18).
UNTOUCHED_SPAN_DAYS = 7

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


def _slot(w: dict) -> Tuple[str, str]:
    """The day and the sport a session stands in; one session per slot."""
    return (w['date'], canonical_sport(w.get('sport_type') or ''))


def _named(w: dict) -> str:
    """'Easy run, 40 min': the title and the length the list sets after the day."""
    title = w.get('title') or w.get('sport_type') or 'Session'
    minutes = w.get('duration_minutes')
    if not minutes:
        return title
    return f"{title}, {minutes} min"


def _now_line(w: dict, today: str) -> str:
    """A session the day holds after the change: '🚴 Tue 10 · Easy ride, 60 min'."""
    return f"{sport_emoji(w.get('sport_type'))} {_list_day(w['date'], today)} · {_named(w)}"


def _was(w: dict, where: str = "") -> str:
    """What a day held before, 'was 🚴 Easy ride, 60 min', with '→ Tue 10' or '→ dropped' when
    it left the day. A rest day reads "was a rest day"."""
    if _is_rest(w):
        return "was a rest day"
    was = f"was {sport_emoji(w.get('sport_type'))} {_named(w)}"
    if not where:
        return was
    return f"{was} → {where}"


def _same_session_line(pw: dict, original: dict) -> str:
    """Under a session that stays on its day: the planner's change line when it kept its title,
    else what it was (§3, D18)."""
    change = (pw.get('change') or '').strip()
    kept = (original.get('title'), canonical_sport(original.get('sport_type') or ''))
    if change and kept == (pw.get('title'), canonical_sport(pw.get('sport_type') or '')):
        return change
    if _named(original) == _named(pw) and not _is_rest(original):
        return "wording updated"
    return _was(original)


def _day_entries(proposal: RevisionProposal) -> List[Tuple[str, str, bool]]:
    """`(date, lines, changed)` per day the list shows, in date order (§3, D18). A changed day
    lists the sessions it holds after the change, then each session it held before and holds
    no more, with "→" and the day it moved to, or "dropped". The days in between that do not
    change are listed too, "(unchanged)", when every changed day fits in one week."""
    today = _today_str()
    moved_to: Dict[Tuple[str, str], str] = {}
    continued = set()
    for pair in proposal.pairs:
        pw, original = pair.proposal, pair.original
        source = pw.get('replaces_slot')
        if source:
            source = (source[0], canonical_sport(source[1]))
        if source and source[0] != pw['date']:
            moved_to[source] = pw['date']
            continue
        if original and original['date'] == pw['date'] and source in (None, _slot(original)):
            continued.add(_slot(original))

    new_by_day: Dict[str, List[Any]] = {}
    for pair in proposal.pairs:
        new_by_day.setdefault(pair.proposal['date'], []).append(pair)
    taken = {_slot(pair.proposal) for pair in proposal.pairs}
    removed = {_slot(w) for w in proposal.removals}
    held = {(day, canonical_sport(sport)) for day, sport in proposal.held}

    stays: Dict[str, List[dict]] = {}
    leaves: Dict[str, List[str]] = {}
    had = set()
    for w in proposal.before:
        slot = _slot(w)
        had.add(w['date'])
        if slot in continued:
            continue
        if slot in moved_to:
            where = _list_day(moved_to[slot], today)
        elif slot in removed or slot in taken or (w['date'] in new_by_day and slot not in held):
            where = "dropped"
        else:
            stays.setdefault(w['date'], []).append(w)
            continue
        leaves.setdefault(w['date'], []).append(_was(w, where))

    changed = sorted(set(new_by_day) | set(leaves))
    if not changed:
        return []
    fits_a_week = shift(changed[0], UNTOUCHED_SPAN_DAYS) > changed[-1]
    days = set(changed)
    if fits_a_week:
        days |= {day for day in stays if changed[0] < day < changed[-1]}
    entries = []
    for day in sorted(days):
        lines = []
        for pair in new_by_day.get(day, []):
            lines.append(_now_line(pair.proposal, today))
            if pair.original and _slot(pair.original) in continued:
                lines.append(REPLACED_INDENT + _same_session_line(pair.proposal, pair.original))
        lines += [f"{_now_line(w, today)} {UNCHANGED}" for w in stays.get(day, [])]
        if not lines:
            lines.append(f"{sport_emoji('rest')} {_list_day(day, today)} · {NOTHING_PLANNED}")
        lines += [REPLACED_INDENT + line for line in leaves.get(day, [])]
        if day not in had:
            lines.append(f"{REPLACED_INDENT}nothing was planned")
        entries.append((day, "\n".join(lines), day in changed))
    return entries


def simple_change_lines(proposal: RevisionProposal) -> List[str]:
    """One entry per day the list shows, in date order (§3, D18). Every session the proposal
    changes, moves or removes is on one."""
    return [lines for _, lines, _ in _day_entries(proposal)]


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


def _before(existing: Optional[dict], text: str, changes: List[Any]) -> str:
    """The whole text of the session a card replaces, "" when the changes already show what
    changed or it reads the same (§6.2)."""
    if not existing or changes:
        return ""
    before = (existing.get('description') or '').strip()
    return "" if before == text else before


def _page_changes(pw: dict, existing: dict) -> List[List[Dict[str, Any]]]:
    """The changed passages for the page, which draws and flows them itself: per passage, its
    sides, each with its side, its label and its stretches of words (§6.2)."""
    marks = {GONE: SIMPLE_GONE_MARK, CAME: SIMPLE_NEW_MARK}
    return [
        [{"side": side, "label": f"{marks[side]}{label}", "parts": parts}
         for side, label, parts in wording_group_sides(group)]
        for group in wording_groups(pw, existing)
    ]


def page_content(proposal: RevisionProposal) -> Dict[str, Any]:
    """What the details page shows of the proposal (§6.2): the summary, then one card per
    changed session in date order. A card is its line, its own reason, the changed passages
    when only its text changed, its whole new text, shown open when there is no passage to
    read first, and the whole text of what it replaces or drops. The first card of a day
    opens with that day's lines in the chat, and a changed day with no card of its own gets
    a card of those lines alone (D18)."""
    today = _today_str()
    cards = []
    for pair in proposal.pairs:
        pw, existing = pair.proposal, pair.original
        text = (pw.get('description') or '').strip()
        changes = _page_changes(pw, existing) if rewritten_text_only(pw, existing) else []
        cards.append((pw['date'], {
            "line": _now_line(pw, today), "why": _own_reason(pw, proposal),
            "changes": changes, "text": text, "before": _before(existing, text, changes),
            "open": not changes,
        }))
    for ew in proposal.removals:
        cards.append((ew['date'], {
            "line": f"{_now_line(ew, today)} → dropped",
            "text": (ew.get('description') or '').strip(),
        }))
    days = {day: lines for day, lines, changed in _day_entries(proposal) if changed}
    cards.sort(key=lambda entry: entry[0])
    for day, card in cards:
        if day in days:
            card["line"] = days.pop(day)
    cards += [(day, {"line": lines}) for day, lines in days.items()]
    return {
        "summary": (proposal.reason or '').strip(),
        "cards": [card for _, card in sorted(cards, key=lambda entry: entry[0])],
        "notice": proposal.strength_notice or "",
    }
