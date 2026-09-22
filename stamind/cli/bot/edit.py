"""`bot capture edit_goal` and `bot capture edit_constraint` (§12.4).

The two intents that change a row the athlete already has. They are the only captures
where the model nominates WHICH row is meant, so everything here exists to keep that
nomination honest: it may only name a row this command showed it, the preview is drawn
from the stored row rather than from what the model believes the row says, and two or
more plausible rows become a picker whose leaves re-enter this same flow with the row
pinned.

A nomination that lands on a session instead is not an edit at all: the ask was coach
territory, so it offers to hand the athlete's own words to `workout adapt -m` (§12.3).
"""
import argparse
import shlex
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind import runtime
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find, nominate_rows,
    upcoming_sessions, valid_date,
)
from stamind.cli.render.plan_lines import (
    picker_label, simple_constraint_edit_lines, simple_goal_edit_lines, simple_goal_line,
)
from stamind.cli.render.session_lines import simple_day_word, simple_session_line
from stamind.sentinels import emit_buttons
from stamind.text import wrap_text
from stamind.clock import today_str as _today_str
import stamind.cli.constraints as _constraints
import stamind.cli.goals as _goals
import stamind.cli.workouts.adapt as _adapt


def _hand_off_to_coach(text: str) -> None:
    """Runs `workout adapt -m` with the athlete's original words, in this process. The
    coach reads what she wrote, which is the whole point of this lane (§12.3, §12.4)."""
    _adapt.run_workout_adapt(argparse.Namespace(
        date=None, no_pull=False, force_pull=False, auto=False,
        message=text, lookback=None,
    ))


# --- capture: the edits, which nominate their object (§12.4) ---

# The one clause §7 relaxes for edits, stated where the prompts that rely on it live:
# the model may NOMINATE an object, but the preview is rendered by the CLI from the real
# row, and nothing executes without the athlete's confirmation on it.

EDIT_PROMPT = (
    CAPTURE_ROLE
    + "## TASK\n\n"
    "{dated}\n\n"
    "The athlete wants to change something they already have. Decide WHICH of the rows\n"
    "below they mean, and what the message changes about it.\n\n"
    "Nominate the way a person would. The athlete's words do not respect the app's\n"
    'categories — "my long run" names a session, "my marathon" names a goal — so you are\n'
    "shown both kinds of row and only the data says which reading is plausible. Pick the\n"
    "ONE row the message most plausibly means, from EITHER list.\n\n"
    '- A {domain} row -> "kind": "{domain}" with its id.\n'
    '- A session on the schedule -> "kind": "session" with its id. The app hands those to\n'
    "  the coach; you do not write the change.\n"
    "- Two or more rows equally plausible -> nominate the best one AND list every plausible\n"
    '  id in "candidate_ids". The athlete picks from them.\n'
    '- Nothing here matches -> "kind": "none".\n\n'
    '"changes" carries ONLY the fields the message actually states, for a {domain} row:\n'
    "{fields}\n"
    + NEVER_FILL_RULE
    + "\n## {domain_upper}S\n\n{rows}\n"
    "\n## SESSIONS ON THE SCHEDULE\n\n{sessions}\n"
    "\n## RESPONSE FORMAT\n\n"
    "You MUST respond with a JSON object containing:\n"
    "{{\n"
    '  "kind": "{domain}" | "session" | "none",\n'
    '  "id": <the id of the row you nominate, or null>,\n'
    '  "candidate_ids": [<ids>, ...]  // only when several are equally plausible\n'
    '  "changes": {{ ... }}\n'
    "}}\n"
)

GOAL_EDIT_FIELDS = (
    '  "title": the goal renamed, "target_date": "YYYY-MM-DD", "description": free text.\n'
    "  A goal's sports, its status and whether its date is an event or a horizon are NOT\n"
    "  yours to change here — leave them out entirely."
)

CONSTRAINT_EDIT_FIELDS = (
    '  "title": the rule restated, "start_date"/"end_date": "YYYY-MM-DD",\n'
    '  "description": free text. Whether a rule forces rest, or reshapes the plan, is NOT\n'
    "  yours to change here — leave those out entirely."
)


# The wrong-domain answer §12.4 replaces a picker with: the ask was coach territory all
# along, so the preview offers the hand-off instead of listing goals at a question about a
# session. It says which reading was dropped, so the router's echo a moment earlier
# ("sounds like a change to a goal") has its correction on screen, and what a "yes"
# sets in motion, because the help card is not on screen at that moment.
SESSION_HANDOFF_ASK = (
    "I don't see a {noun} for that — it sounds like {named}. Shall I pass it to your "
    "coach? They'll reread the coming days with it in mind and propose changes for you "
    "to confirm."
)


def _row_lines(domain: str, rows: Sequence[Dict[str, Any]]) -> str:
    """The domain rows as prompt context: ids and the fields a nomination turns on."""
    if not rows:
        return "(none)"
    if domain == "goal":
        return "\n".join(
            f"- id {g['id']}: \"{g['title']}\" — {g['date_type']} on {g['target_date']}"
            + (f" ({g['description']})" if g.get("description") else "")
            for g in rows
        )
    return "\n".join(
        f"- id {c['id']}: \"{c['title']}\" — {c['start_date']} to {c['end_date']}"
        + (f" ({c['description']})" if c.get("description") else "")
        for c in rows
    )


def _session_lines(sessions: Sequence[Dict[str, Any]]) -> str:
    if not sessions:
        return "(none)"
    return "\n".join(
        f"- id {w['id']}: \"{w.get('title') or w.get('sport_type')}\" on {w['date']}"
        for w in sessions
    )


def _row_id(raw: Any, by_id: Dict[int, Dict[str, Any]]) -> Optional[int]:
    """An id the extraction named, when it names a row this command actually offered.

    A model that answers "3" rather than 3 is nominating the same row, so the string is
    read; an id outside the rows it was shown is not read at all — that is the clause
    keeping a nomination inside the context the CLI gave it (§12.9)."""
    try:
        row_id = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return row_id if row_id in by_id else None


def edit_capture(domain: str, text: str, pinned_id: Optional[int]) -> None:
    """The shared body of `edit_goal` and `edit_constraint` (§12.4).

    Every path ends at a CLI-rendered preview and a tap — the picker fallback included,
    whose leaves re-enter this function with the nomination pinned rather than executing
    anything themselves. That is what makes the relaxed clause survive its own fallback."""
    today = _today_str()
    rows = nominate_rows(domain, today)
    by_id = {int(r["id"]): r for r in rows}
    if not rows:
        no_find(text)
        return
    sessions = upcoming_sessions(today)
    prompt = EDIT_PROMPT.format(
        dated=dated_context(today), domain=domain, domain_upper=domain.upper(),
        fields=GOAL_EDIT_FIELDS if domain == "goal" else CONSTRAINT_EDIT_FIELDS,
        rows=_row_lines(domain, rows), sessions=_session_lines(sessions),
    )
    if pinned_id is not None:
        prompt += (
            f"\n## ALREADY DECIDED\n\nThe athlete has picked the row: id {pinned_id}. "
            f'Return "kind": "{domain}" and that id, and fill "changes" for THAT row.\n'
        )
    data = capture_call(prompt, text, f"bot_capture_edit_{domain}")
    if data is None:
        no_find(text)
        return

    kind = str(data.get("kind") or "none")
    changes = data.get("changes") if isinstance(data.get("changes"), dict) else {}
    if pinned_id is not None:
        # A pin comes from a leaf this command built, so a pin that no longer resolves is
        # a row removed since — and must not fall back to whatever the model nominated.
        if pinned_id not in by_id:
            no_find(text)
            return
        kind, row_id = domain, pinned_id
    else:
        row_id = _row_id(data.get("id"), by_id)

    if kind == "session" and pinned_id is None:
        _offer_session_handoff(domain, data, sessions, text, today)
        return
    if kind != domain or row_id is None:
        no_find(text)
        return

    # De-duplicated: "several close candidates" is a count of ROWS, and a model that
    # names the same one twice has not made the question harder.
    candidates = list(dict.fromkeys(
        i for i in (_row_id(c, by_id) for c in data.get("candidate_ids") or [])
        if i is not None
    ))
    if pinned_id is None and len(candidates) > 1:
        _offer_row_picker(domain, [by_id[i] for i in candidates], text, today)
        return

    row = by_id[row_id]
    lines, kwargs = _edit_preview(domain, row, changes, today)
    if not kwargs:
        # The nomination landed but the message changed nothing this surface may write —
        # a tier or a sport, which stay expert vocabulary (§12.4).
        no_find(text)
        return
    for line in lines:
        print(wrap_text(line))
    if not runtime.prompt.confirm("Shall I make that change?"):
        # A wrong nomination dies visibly here, and the picker is the way back to the
        # right row rather than a dead end (§12.4).
        others = [r for r in rows if int(r["id"]) != row_id]
        print("Okay — nothing changed.")
        if others:
            _offer_row_picker(domain, others, text, today, declined=True)
        return
    _apply_edit(domain, row_id, kwargs)


def _offer_session_handoff(
    domain: str, data: dict, sessions: Sequence[Dict[str, Any]], text: str, today: str
) -> None:
    """A nomination that landed on a session: the ask was coach territory all along, so
    the preview offers the hand-off and the confirm runs `adapt -m` with her own words."""
    session = next(
        (w for w in sessions
         if _row_id(data.get("id"), {int(w["id"]): w}) is not None), None
    )
    if session is None:
        no_find(text)
        return
    named = simple_session_line(session, lead=simple_day_word(session["date"], today))
    noun = "goal" if domain == "goal" else "rule"
    if not runtime.prompt.confirm(SESSION_HANDOFF_ASK.format(noun=noun, named=named)):
        print("Okay — I'll leave it.")
        return
    _hand_off_to_coach(text)


def _offer_row_picker(
    domain: str, rows: Sequence[Dict[str, Any]], text: str, today: str,
    declined: bool = False,
) -> None:
    """Several close candidates, or a "no" on the preview: the athlete picks the row.

    A leaf does NOT execute the edit — it re-runs this capture with the nomination
    pinned, which re-enters the ordinary preview and confirm (§12.4)."""
    intent = "edit_goal" if domain == "goal" else "edit_constraint"
    print("Which one did you mean?" if not declined else "Which one should I change?")
    for row in rows:
        print(_picker_row_line(domain, row, today))
    leaves = [
        {"label": _picker_label(row["title"]),
         "send": f"bot capture {intent} --id {row['id']} {shlex.quote(text)}"}
        for row in rows
    ]
    emit_buttons(leaves + [{"label": "✖️ None of these",
                            "ack": "No problem — tell me again in your own words 💬"}])


def _picker_label(title: str) -> str:
    return f"✏️ {picker_label(title)}"


def _picker_row_line(domain: str, row: Dict[str, Any], today: str) -> str:
    if domain == "goal":
        return "• " + simple_goal_line(row, today)
    return "• " + f"{row['title']} — " + simple_day_word(row["start_date"], today)


def _edit_preview(
    domain: str, row: Dict[str, Any], changes: Dict[str, Any], today: str
) -> Tuple[List[str], Dict[str, Any]]:
    """The preview lines, and the fields the edit would actually write.

    Rendered from the real row, never from what the model believes the row says — which
    is what makes a wrong nomination visible ("Your goal Marathon (Sat Oct 26) → move to
    Sun Oct 12") rather than plausible (§12.4)."""
    if domain == "goal":
        kwargs: Dict[str, Any] = {}
        title = str(changes.get("title") or "").strip()
        if title and title != row["title"]:
            kwargs["title"] = title
        target = valid_date(changes.get("target_date"))
        if target and target != str(row["target_date"]):
            kwargs["target_date"] = target
        description = changes.get("description")
        if description is not None and str(description).strip() != (
            row.get("description") or ""
        ):
            kwargs["description"] = str(description).strip()
        return simple_goal_edit_lines(row, kwargs, today), kwargs

    kwargs = {}
    title = str(changes.get("title") or "").strip()
    if title and title != row["title"]:
        kwargs["title"] = title
    for field, key in (("start_date", "start_date"), ("end_date", "end_date")):
        value = valid_date(changes.get(field))
        if value and value != str(row[key]):
            kwargs[key] = value
    description = changes.get("description")
    if description is not None and str(description).strip() != (
        row.get("description") or ""
    ):
        kwargs["description"] = str(description).strip()
    # The dates only make sense as a pair: a new start past the stored end would be
    # refused by the command, so the window closes on the day it opens instead.
    if kwargs.get("start_date") and kwargs["start_date"] > kwargs.get(
        "end_date", str(row["end_date"])
    ):
        kwargs["end_date"] = kwargs["start_date"]
    return simple_constraint_edit_lines(row, kwargs, today), kwargs


def _apply_edit(domain: str, row_id: int, kwargs: Dict[str, Any]) -> None:
    """Runs the real command, with argv the CLI assembled from the confirmed proposal —
    never authored by the model (§12.9)."""
    if domain == "goal":
        _goals.run_goal_edit(argparse.Namespace(
            id=row_id, title=kwargs.get("title"),
            target_date=kwargs.get("target_date"), sport=None,
            desc=kwargs.get("description"), status=None, date_type=None,
        ))
        return
    _constraints.run_constraint_edit(argparse.Namespace(
        id=row_id, title=kwargs.get("title"), start=kwargs.get("start_date"),
        end=kwargs.get("end_date"), rest=None, desc=kwargs.get("description"),
        replan=None,
    ))
