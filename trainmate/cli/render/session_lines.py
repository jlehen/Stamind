"""The companion voice on a day and what was trained in it
(DESIGN_bot_simple_frontend.md §6).

Pure functions over rows: one session as a line, a day, a week, a compare, a revision,
and the words for a date — "today", "tomorrow", "Thu 28 Aug". `bot morning` and the
week view call them directly, never through a renderer (DESIGN_render_persona.md §3),
which is why they are a module and not methods.

`plan_lines.py` is the other half of the voice, and borrows the date words from here."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from trainmate.strength.sets import activity_lines
from trainmate.coach.proposals import RevisionProposal
from trainmate.sports import canonical_sport
from trainmate.text import wrap_text
from trainmate.clock import days_between, fmt_date, today_str as _today_str
from trainmate.cli.workouts.revisions import (
    quotes_wording, rewritten_text_only, wording_group_lines, wording_groups,
)


REST_DAY_LINE = "Rest day — enjoy it 🎉"

# A session the athlete has already trained, in companion voice. Only `done` and
# `partial` earn a line — DESIGN_bot_simple_frontend.md §6 says why the other verdicts
# say nothing at all. The statuses are a constant because the morning push reads them
# too, and "already trained" has to mean the same thing on both surfaces (§4.1).
SIMPLE_DONE_LINE = "✅ Already done — nice work 💪"
SIMPLE_DONE_STATUSES = ("done", "partial")

# Emoji per canonical sport for the simple session lines, keyed by the names in
# `sports.CANONICAL_SPORTS`; unknown sports get the generic one rather than nothing,
# so a new sport never renders bare. `rest` is in the table so a taper week reads as
# intended rest rather than as a generic session (DESIGN_runway_nudge.md §6).
SPORT_EMOJI = {
    "running": "🏃",
    "cycling": "🚴",
    "hiking": "🥾",
    "strength_training": "🏋️",
    "yoga": "🧘",
    "ski_touring": "🎿",
    "rowing": "🚣",
    "downhill_skiing": "⛷️",
    "rest": "🛌",
}
DEFAULT_SPORT_EMOJI = "🎽"


def sport_emoji(sport_type: Optional[str]) -> str:
    """The emoji standing in for the sport column in simple session lines."""
    return SPORT_EMOJI.get((sport_type or "").strip().lower(), DEFAULT_SPORT_EMOJI)


# Where one session's text ends and the next begins. A blank line cannot say it: a
# prescription and a wording diff both use blank lines inside themselves
# (DESIGN_bot_simple_frontend.md §6).
SIMPLE_SESSION_RULE = "———"


def simple_session_line(w: Dict[str, Any], lead: Optional[str] = None) -> str:
    """One simple-mode line for a session: '🏃 Today: Easy run — 40 min'.

    `lead` is the day word ('Today', '2026-08-25 Tue'); omitted for a bare line."""
    duration = w.get("duration_minutes")
    duration_str = f" — {duration} min" if duration else ""
    prefix = f"{sport_emoji(w.get('sport_type'))} "
    if lead:
        prefix += f"{lead}: "
    return f"{prefix}{w.get('title') or w.get('sport_type', 'Session')}{duration_str}"


def simple_day_lines(
    workouts: List[Dict[str, Any]], date_str: str,
    verdicts: Optional[Dict[int, Dict[str, Any]]] = None,
) -> List[str]:
    """Simple rendering of one day's schedule: session line(s) plus the wrapped
    description (the week planner's actual prescription), or the one-line rest message.
    Any empty day gets the rest line, whatever the reason it is empty
    (DESIGN_bot_simple_frontend.md §10).

    `verdicts` is `adherence_verdicts`' map; a session already trained gets the done
    line, and every other verdict renders as it did before (§6 tone rule)."""
    if not workouts:
        return [REST_DAY_LINE]
    day_word = "Today" if date_str == _today_str() else fmt_date(date_str)
    lines: List[str] = []
    for w in workouts:
        if lines:
            lines.append(f"\n{SIMPLE_SESSION_RULE}\n")
        lines.append(simple_session_line(w, lead=day_word))
        status = ((verdicts or {}).get(w.get("id")) or {}).get("status")
        if status in SIMPLE_DONE_STATUSES:
            lines.append(SIMPLE_DONE_LINE)
        description = (w.get("description") or "").strip()
        if description:
            lines.append(wrap_text(description))
    return lines


def simple_week_lines(
    workouts: List[Dict[str, Any]],
    verdicts: Optional[Dict[int, Dict[str, Any]]] = None,
    end_note: Optional[str] = None,
) -> List[str]:
    """Simple rendering of a multi-day window: one dated line per session, no
    descriptions, ending on an encouraging count. An empty window is a break, not
    a gap (§6 tone rule).

    `verdicts` is `adherence_verdicts`' map; a session already trained gets a ✅
    instead of its sport emoji, so the listing doubles as her calendar — done behind,
    plan ahead (DESIGN_bot_simple_frontend.md §11).

    `end_note` names the end of the schedule when the window crosses it, the companion
    form of the expert listing's marker (DESIGN_runway_nudge.md §6)."""
    if not workouts:
        # An empty window past the cliff is the schedule having run out, not a break the
        # coach chose — so the note replaces the break line rather than following it (§4).
        return [end_note] if end_note else ["Nothing on the schedule — enjoy the break 🎉"]
    lines = ["🗓 Coming up:"]
    done = 0
    for w in workouts:
        day = datetime.strptime(w["date"], "%Y-%m-%d").strftime("%a %d")
        status = ((verdicts or {}).get(w.get("id")) or {}).get("status")
        if status in SIMPLE_DONE_STATUSES:
            done += 1
            lines.append(f"{day} · ✅ {simple_session_line(w)}")
        else:
            lines.append(f"{day} · {simple_session_line(w)}")
    if end_note:
        lines.append(end_note)
    count = len(workouts)
    session_word = "session" if count == 1 else "sessions"
    if done:
        lines.append(f"\n{done} of {count} {session_word} already done — keep it rolling 💪")
    else:
        lines.append(f"\n{count} {session_word} planned — you've got this 💪")
    return lines


def simple_activity_line(act: Dict[str, Any]) -> str:
    """One completed activity in companion words: '🚴 Morning Ride — 90 min'."""
    name = act.get("activity_name") or act.get("activity_type") or "Activity"
    emoji = sport_emoji(canonical_sport(act.get("activity_type")))
    return f"{emoji} {name} — {simple_activity_minutes(act)} min"


def simple_set_lines(act: Dict[str, Any]) -> List[str]:
    """What was lifted, under a strength session's line (DESIGN_strength_tracking.md §7)."""
    return [f"      {line}" for line in activity_lines(act)]


def simple_activity_minutes(act: Dict[str, Any]) -> int:
    return round((act.get("duration_sec") or 0) / 60)


def simple_compare_lines(
    days: List[Tuple[str, list, list]], start: str, end: str, today: str,
) -> List[str]:
    """Simple rendering of a look back: one dated line per planned session and per
    extra activity, in a four-glyph vocabulary that needs no legend — ✅ followed the
    plan, ❌ did not, ➕ an effort the plan did not ask for, ⏳ still ahead today
    (DESIGN_bot_simple_frontend.md §6). A kept rest day is a ✅ like any other session;
    a rest day trained through is a ❌ that says what was done instead.

    `days` is `compare_days`' list; the caller has already dropped the efforts too small
    to mention. The closing count follows the §6 tone rule: what was done leads, the
    gap is a plain number after it, and a window with nothing behind it is not a miss."""
    lines = [f"🔎 Looking back, {simple_span_words(start, end, today)}:"]
    total = done = 0
    for date_str, results, unplanned in days:
        day = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %d")
        for r in results:
            w = r["planned"]
            act = r["completed"]
            if w["sport_type"] == "rest":
                if act:
                    lines.append(
                        f"{day} · ❌ 🛌 Rest day, but you trained: {simple_activity_line(act)}"
                    )
                    lines.extend(simple_set_lines(act))
                elif r.get("pending"):
                    lines.append(f"{day} · 🛌 Rest day")
                else:
                    lines.append(f"{day} · ✅ 🛌 Rest day")
                continue
            if r.get("pending"):
                lines.append(f"{day} · ⏳ {simple_session_line(w)}")
                continue
            total += 1
            if act:
                done += 1
                lines.append(
                    f"{day} · ✅ {simple_session_line(w)} "
                    f"(you did {simple_activity_minutes(act)} min)"
                )
                lines.extend(simple_set_lines(act))
            else:
                lines.append(f"{day} · ❌ {simple_session_line(w)}")
        for act in unplanned:
            lines.append(f"{day} · ➕ {simple_activity_line(act)}, not on the plan")
            lines.extend(simple_set_lines(act))
    if len(lines) == 1:
        return ["Nothing to look back on yet — your sessions are ahead of you 💪"]
    session_word = "session" if total == 1 else "sessions"
    if total == 0:
        lines.append("\nNo sessions were due — rest well 🎉")
    elif done == total:
        lines.append(f"\nAll {total} {session_word} done — brilliant 🎉")
    elif done:
        lines.append(f"\n{done} of {total} {session_word} done — keep it rolling 💪")
    else:
        lines.append(f"\n0 of {total} {session_word} done — the plan is ready when you are 💪")
    return lines


def simple_date_word(date_str: str) -> str:
    """A date in companion words — 'Sat Sep 26' — no ISO form, no year (§6). The
    countdown beside it (`simple_when`) carries the year information a reader needs."""
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %b %d")


def simple_when(date_str: str, today: str) -> str:
    """How far away a date is, in companion words: 'today', 'tomorrow', days inside two
    weeks, then weeks, then months. Rough on purpose — a countdown is a feeling here,
    not a schedule (DESIGN_bot_simple_frontend.md §11)."""
    days = days_between(today, date_str)
    if days < 0:
        return "passed"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 14:
        return f"in {days} days"
    if days < 112:
        return f"in {round(days / 7)} weeks"
    return f"in {round(days / 30.4)} months"


def simple_day_word(date_str: str, today: str) -> str:
    """One date as the companion names it: 'today', else the day word (§6)."""
    return "today" if date_str == today else simple_date_word(date_str)


def simple_span_words(start: str, end: str, today: str) -> str:
    """A window in companion words: one day word, or 'Thu Sep 04 to Sun Sep 07'. The
    companion never shows an ISO span, on any surface that renders one (§6)."""
    span = simple_day_word(start, today)
    if end != start:
        span = f"{span} to {simple_day_word(end, today)}"
    return span


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
    for pair in proposal.pairs:
        pw, existing = pair.proposal, pair.original
        day = "Today" if pw['date'] == today else simple_date_word(pw['date'])
        entry_lines = [
            f"{simple_session_line(pw, lead=day)} "
            f"({_simple_was_clause(pw, existing, today)})"
        ]
        why = (pw.get('modification_reason') or '').strip()
        if why and why != (proposal.reason or '').strip():
            entry_lines.append(why)
        paragraphs = ["\n".join(entry_lines)]
        if quotes_wording(pw, existing):
            # A blank line between pairs, so each Was/Now pair reads as one passage.
            paragraphs.extend(
                "\n".join(wording_group_lines(b)) for b in wording_groups(pw, existing)
            )
        entries.append((pw['date'], "\n\n".join(paragraphs)))
    for ew in proposal.removals:
        day = "Today" if ew['date'] == today else simple_date_word(ew['date'])
        entries.append((ew['date'], f"🗑 {day}: {ew['title']} — dropped"))
    entries.sort(key=lambda e: e[0])
    return [text for _, text in entries]
