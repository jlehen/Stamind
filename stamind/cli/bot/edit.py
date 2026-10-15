"""`bot capture edit_goal` and `bot capture edit_constraint` (§12.4), and the two queue
kinds they ask through: `edit`, "Shall I change this constraint?", and `pick`, "Which
constraint did you mean?" (DESIGN_chat_questions.md §4, §5).

The two intents that change a row the athlete already has. They are the only captures
where the model nominates WHICH row is meant, so everything here exists to keep that
nomination honest: it may only name a row this command showed it, the question is drawn
from the stored row rather than from what the model believes the row says, and two or
more plausible rows become a picker whose answers re-enter this same flow with the row
pinned.

A nomination that lands on a session instead is not an edit at all: the ask was coach
territory, so it saves the question whether to hand the athlete's own words to `workout
adapt -m` (§12.3, DESIGN_long_runs_beside_chat.md §5).

A terminal asks on the spot. In the chat each question is saved, and the command sends it.
"""
import argparse
from typing import Any, Dict, List, Optional, Sequence

from stamind import clock, runtime
from stamind.cli.bot import hand_off
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find, nominate_rows,
    upcoming_sessions, valid_date,
)
from stamind.cli.bot.route import use_fast_model
from stamind.cli.render.plan_lines import (
    picker_label, simple_constraint_edit_lines, simple_goal_edit_lines, simple_goal_line,
)
from stamind.cli.render.session_lines import simple_day_word, simple_session_line
from stamind.clock import today_str as _today_str
from stamind.db.queue import queue_stamp
from stamind.prompt import Choice, athlete_watching
from stamind.queue_kind import QUESTION, YES, YES_NO, Kind, queue, queue_replacing
from stamind.text import wrap_text
import stamind.cli.constraints as _constraints
import stamind.cli.goals as _goals

EDIT = "edit"
PICK = "pick"
NOTHING_CHANGED_LINE = "Okay — nothing changed."
NONE_OF_THESE = "✖️ None of these"
NONE_LINE = "No problem — tell me again in your own words 💬"

# The part of a goal or a constraint each field changes: a newer question closes an older
# one about the same row when it changes every part the older one would
# (DESIGN_chat_questions.md §4).
PARTS = {
    "title": "name", "description": "note",
    "target_date": "dates", "start_date": "dates", "end_date": "dates",
}


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
    '  "title": the constraint restated, "start_date"/"end_date": "YYYY-MM-DD",\n'
    '  "description": free text. Whether a constraint forces rest, or reshapes the plan, is\n'
    "  NOT yours to change here — leave those out entirely."
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


def edit_capture(domain: str, text: str, pinned_id: Optional[int] = None) -> None:
    """The shared body of `edit_goal` and `edit_constraint` (§12.4).

    Every path ends at a question drawn from the stored row — the picker fallback included,
    whose answers re-enter this function with the nomination pinned rather than executing
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
        _pick(domain, [by_id[i] for i in candidates], text, today)
        return

    row = by_id[row_id]
    changes = _edit_changes(domain, row, changes)
    if not changes:
        # The nomination landed but the message changed nothing this surface may write —
        # a tier or a sport, which stay expert vocabulary (§12.4).
        no_find(text)
        return
    if athlete_watching():
        queue_replacing(EDIT, {
            "domain": domain, "row": row_id, "was": row, "changes": changes, "text": text,
            "answers": list(YES_NO),
        }, about=f"{domain}:{row_id}", parts={PARTS[field] for field in changes})
        return
    if not runtime.prompt.confirm(wrap_text(_edit_question(domain, row, changes, today))):
        _declined(domain, row_id, text)
        return
    _apply_edit(domain, row_id, changes)


def _offer_session_handoff(
    domain: str, data: dict, sessions: Sequence[Dict[str, Any]], text: str, today: str
) -> None:
    """A nomination that landed on a session: the ask was coach territory all along, so
    the hand-off question is saved, and this command ends. Its "Yes" runs `adapt -m` with
    her own words (DESIGN_long_runs_beside_chat.md §5)."""
    session = next(
        (w for w in sessions
         if _row_id(data.get("id"), {int(w["id"]): w}) is not None), None
    )
    if session is None:
        no_find(text)
        return
    named = simple_session_line(session, lead=simple_day_word(session["date"], today))
    noun = "goal" if domain == "goal" else "constraint"
    hand_off.queue_question(noun, named, session, text)


def _declined(domain: str, row_id: int, text: str) -> None:
    """"No" on the question: a wrong nomination dies visibly here, and the picker is the
    way back to the right row rather than a dead end (§12.4)."""
    print(NOTHING_CHANGED_LINE)
    today = _today_str()
    others = [row for row in nominate_rows(domain, today) if int(row["id"]) != row_id]
    if others:
        _pick(domain, others, text, today, declined=True)


def _pick_ask(domain: str, declined: bool) -> str:
    if declined:
        return f"Which {domain} should I change?"
    return f"Which {domain} did you mean?"


def _picker_row_line(domain: str, row: Dict[str, Any], today: str) -> str:
    if domain == "goal":
        return simple_goal_line(row, today)
    return f"{row['title']} — " + simple_day_word(row["start_date"], today)


def _pick(
    domain: str, rows: Sequence[Dict[str, Any]], text: str, today: str,
    declined: bool = False,
) -> None:
    """Several close candidates, or a "No" on the question: the athlete picks the row.

    A pick does NOT execute the edit — it reads the message again with the row pinned,
    which re-enters the ordinary question (§12.4)."""
    if athlete_watching():
        queue(PICK, queue_stamp(clock.command_start()), {
            "domain": domain, "text": text, "declined": declined,
            "answers": [
                {"label": f"✏️ {picker_label(row['title'])}", "row": int(row["id"])}
                for row in rows
            ] + [{"label": NONE_OF_THESE}],
        })
        return
    picked = runtime.prompt.choose(
        _pick_ask(domain, declined),
        [Choice(str(row["id"]), _picker_row_line(domain, row, today)) for row in rows]
        + [Choice("none", NONE_OF_THESE)],
        default="none",
    )
    if picked == "none":
        print(NONE_LINE)
        return
    edit_capture(domain, text, int(picked))


def _edit_changes(
    domain: str, row: Dict[str, Any], changes: Dict[str, Any]
) -> Dict[str, Any]:
    """The fields the edit would actually write: those the message changes, read against
    the real row, never against what the model believes the row says (§12.4)."""
    kwargs: Dict[str, Any] = {}
    title = str(changes.get("title") or "").strip()
    if title and title != row["title"]:
        kwargs["title"] = title
    dates = ("target_date",) if domain == "goal" else ("start_date", "end_date")
    for field in dates:
        value = valid_date(changes.get(field))
        if value and value != str(row[field]):
            kwargs[field] = value
    description = changes.get("description")
    if description is not None and str(description).strip() != (
        row.get("description") or ""
    ):
        kwargs["description"] = str(description).strip()
    # The dates only make sense as a pair: a new start past the stored end would be
    # refused by the command, so the window closes on the day it opens instead.
    if domain != "goal" and kwargs.get("start_date") and kwargs["start_date"] > kwargs.get(
        "end_date", str(row["end_date"])
    ):
        kwargs["end_date"] = kwargs["start_date"]
    return kwargs


def _edit_question(
    domain: str, row: Dict[str, Any], changes: Dict[str, Any], today: str
) -> str:
    """The row as it is beside what it would become, then the question. Drawn from the
    stored row, which is what makes a wrong nomination visible ("Your goal Marathon (Sat
    Oct 26) → move to Sun Oct 12") rather than plausible (§12.4)."""
    if domain == "goal":
        lines = simple_goal_edit_lines(row, changes, today)
    else:
        lines = simple_constraint_edit_lines(row, changes, today)
    return "\n".join(lines + [f"Shall I change this {domain}?"])


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


# --- the two queue kinds (DESIGN_chat_questions.md §4, §5) ---

def _current_row(domain: str, row_id: int) -> Optional[Dict[str, Any]]:
    """The goal or constraint as stored now, or None when it is no longer one an edit
    may change."""
    rows = nominate_rows(domain, _today_str())
    return next((row for row in rows if int(row["id"]) == row_id), None)


def _edit_wording(item: Dict[str, Any]) -> str:
    """Drawn from the row as it is each time it is sent, or as it was if it is gone."""
    payload = item["payload"]
    row = _current_row(payload["domain"], payload["row"]) or payload["was"]
    return _edit_question(payload["domain"], row, payload["changes"], _today_str())


def _edit_stale(item: Dict[str, Any]) -> bool:
    """The row is gone, or already reads as asked."""
    payload = item["payload"]
    row = _current_row(payload["domain"], payload["row"])
    return row is None or all(
        str(row.get(field) or "") == value for field, value in payload["changes"].items()
    )


def _apply_edit_answer(item: Dict[str, Any], index: int, text: Optional[str]) -> None:
    """"Yes" makes the change. "No" changes nothing, and asks which row was meant when
    there are others."""
    payload = item["payload"]
    if index == YES:
        _apply_edit(payload["domain"], payload["row"], payload["changes"])
        return
    _declined(payload["domain"], payload["row"], payload["text"])


def _listed_rows(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The rows the picker offers that are still ones an edit may change."""
    payload = item["payload"]
    listed = {answer.get("row") for answer in payload["answers"]}
    return [
        row for row in nominate_rows(payload["domain"], _today_str())
        if int(row["id"]) in listed
    ]


def _pick_wording(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    today = _today_str()
    return "\n".join(
        [_pick_ask(payload["domain"], payload["declined"])]
        + ["• " + _picker_row_line(payload["domain"], row, today) for row in _listed_rows(item)]
    )


def _apply_pick(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """A row reads the athlete's words again with that row named, and asks the edit
    question. "None of these" writes nothing."""
    payload = item["payload"]
    answer = payload["answers"][index]
    if "row" not in answer:
        return NONE_LINE
    use_fast_model(argparse.Namespace())
    edit_capture(payload["domain"], payload["text"], answer["row"])
    return None


# Both are confirmations drawn bare (DESIGN_chat_questions.md §2).
EDIT_KIND = Kind(
    name=EDIT, shape=QUESTION, wording=_edit_wording, companion_wording=_edit_wording,
    is_stale=_edit_stale, apply=_apply_edit_answer, bare=True, confirmation=True,
)
PICK_KIND = Kind(
    name=PICK, shape=QUESTION, wording=_pick_wording, companion_wording=_pick_wording,
    is_stale=lambda item: not _listed_rows(item), apply=_apply_pick, bare=True,
    confirmation=True,
)
