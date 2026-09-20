"""The two questions strength tracking queues for the athlete (DESIGN_strength_tracking.md §7):
are an activity's sets final in Garmin, and what was a group of sets the watch could not name.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from trainmate import clock, runtime
from trainmate.prompt import Choice
from trainmate.queue_kind import QUESTION, Kind, NotApplied
from trainmate.strength import sets, vocabulary
from trainmate.text import capitalized

LEAVE_UNNAMED = "leave it unnamed"
NONE_OF_THESE = "none"
MAX_PROPOSALS = 3

PROPOSE_SYSTEM_PROMPT = """You match what an athlete typed to the exercise names TrainMate knows.

## TASK
The athlete typed the name of a strength exercise they did, in their own words: a machine's
name, a nickname, a misspelling, another language. Pick up to three names from EXERCISE NAMES
that could be that exercise, the most likely first. Copy each name exactly as it is written
there. Prefer the plainest name that fits over a variant the athlete did not mention. Return an
empty list when no name fits.

## EXERCISE NAMES
{names}

## RESPONSE FORMAT
Return a JSON object with exactly this key:
{{"names": ["name", "name"]}}
"""


def activity_words(payload: Dict[str, Any]) -> str:
    """'Tue Sep 15 18:10 gym session'; an item queued before the time was always given has
    none (§7)."""
    day = date.fromisoformat(payload["date"])
    when = f"{day:%a %b} {day.day}"
    if payload.get("time"):
        when += f" {payload['time']}"
    return f"{when} gym session"


def companion_activity_words(item: Dict[str, Any]) -> str:
    """"Tuesday's 18:10 gym session" within the week the question was queued in, "the Sep 1
    18:10 gym session" after it."""
    payload = item["payload"]
    day = date.fromisoformat(payload["date"])
    queued = clock.to_local(datetime.fromisoformat(item["queued_at"])).date()
    start = f" {payload['time']}" if payload.get("time") else ""
    if 0 <= (queued - day).days < 7:
        return f"{day:%A}'s{start} gym session"
    return f"the {day:%b} {day.day}{start} gym session"


def _activity(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return runtime.db.get_completed_activity(item["payload"]["activity_id"])


# --- sets_final: are the sets in Garmin final? ---

def _guessed(payload: Dict[str, Any]) -> List[str]:
    """The exercises the watch named on its own, as the question was queued with them. An
    item queued before phase 2 carries none (§6)."""
    return list(payload.get("guesses") or [])


def _sets_final_wording(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    spans = payload["groups"]
    guesses = _guessed(payload)
    halves = []
    if guesses:
        halves.append(
            f"guessed {len(guesses)} exercise{'s' if len(guesses) != 1 else ''} "
            f"({', '.join(guesses)})"
        )
    if spans:
        listed = ", ".join(sets.positions(first, last) for first, last in spans)
        word = "set" if len(spans) == 1 and spans[0][0] == spans[0][1] else "sets"
        halves.append(
            f"couldn't name {len(spans)} group{'s' if len(spans) != 1 else ''} "
            f"({word} {listed})"
        )
    return (f"{activity_words(payload)}: the watch {' and '.join(halves)}. "
            "Are the sets in Garmin final?")


def _sets_final_companion(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    spans = payload["groups"]
    guesses = _guessed(payload)
    halves = []
    if guesses:
        halves.append(
            f"{len(guesses)} exercise{'s' if len(guesses) != 1 else ''} the watch only "
            "guessed"
        )
    if spans:
        halves.append(
            f"{len(spans)} group{'s' if len(spans) != 1 else ''} of sets it couldn't name"
            if guesses else
            f"{len(spans)} group{'s' if len(spans) != 1 else ''} of sets the watch "
            "couldn't name"
        )
    return (f"{capitalized(companion_activity_words(item))} has {' and '.join(halves)}. "
            "Are the sets in Garmin final?")


def _sets_final_drop(item: Dict[str, Any]) -> str:
    """The drop's label says what it costs: "it's fine" and "yes, final" read alike at
    breakfast, and the wrong tap keeps six names out of the history for good (§7)."""
    if _guessed(item["payload"]):
        return "no, leave it — the watch's names won't count"
    return "no, leave it unnamed"


def _drop_sets_final(item: Dict[str, Any]) -> None:
    """"No, leave it": the sets are frozen as they were first read, the guesses stay
    guesses and the unnamed groups stay unnamed (§7)."""
    activity = _activity(item)
    if activity and not activity["sets_final_at"]:
        runtime.db.freeze_exercise_sets(activity["activity_id"], clock.now())


def _sets_final_stale(item: Dict[str, Any]) -> bool:
    """Settled once the activity is frozen by other means, discarded, or gone."""
    activity = _activity(item)
    return activity is None or bool(activity["discarded"]) or bool(activity["sets_final_at"])


def _apply_sets_final(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    """"Yes, final": reads the sets again, freezes them, makes the guesses still standing
    the athlete's and queues the naming questions."""
    try:
        found = sets.read_again(_activity(item), runtime.garmin.connect())
    except Exception as e:
        raise NotApplied(f"Couldn't read the sets from Garmin ({e}), so nothing changed. "
                         "The question will come back.")
    unnamed = [group for group in found if group.exercise is None]
    if not unnamed:
        return "Sets read again and frozen: every set has a name."
    count = len(unnamed)
    return (f"Sets read again and frozen. {count} group{'s' if count != 1 else ''} still "
            f"without a name: I'll ask about {'it' if count == 1 else 'them'} next time.")


# --- set_names: what was this group? ---

def _set_names_words(item: Dict[str, Any], companion: bool) -> str:
    payload = item["payload"]
    group = (f"{sets.set_span(payload['first'], payload['last'])}: "
             f"{sets.reps_and_load(payload['reps'], payload['load_kg'], companion)}")
    if companion:
        return f"{capitalized(companion_activity_words(item))}, {group}. What was it?"
    return f"{activity_words(payload)}, {group}. What was it?"


def _set_names_stale(item: Dict[str, Any]) -> bool:
    """Settled once the group no longer stands: a set of it has a name, the activity is
    discarded or gone, or `strength reset` froze it again (§7)."""
    payload = item["payload"]
    activity = _activity(item)
    if activity is None or activity["discarded"]:
        return True
    if activity["sets_final_at"] != payload["final_at"]:
        return True
    by_seq = {row["seq"]: row for row in runtime.db.get_exercise_sets(payload["activity_id"])}
    return any(seq not in by_seq or by_seq[seq]["exercise"] for seq in payload["seqs"])


def _apply_set_names(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    payload = item["payload"]
    answer = payload["answers"][index]
    if answer.get("ask"):
        exercise = choose_proposed(text or "")
    else:
        exercise = answer["label"]
    runtime.db.name_exercise_sets(payload["activity_id"], payload["seqs"], exercise)
    return f"Named {sets.set_span(payload['first'], payload['last'])}: {exercise}."


def propose(text: str) -> List[str]:
    """Up to three vocabulary names for what the athlete typed: the one model call in the
    naming path, and every name it returns is checked against the vocabulary (§7)."""
    from trainmate.openrouter import openrouter_client
    system = PROPOSE_SYSTEM_PROMPT.format(names="\n".join(vocabulary.names()))
    result = openrouter_client.complete(
        system, f"## WHAT THE ATHLETE TYPED\n{text}\n", label="strength_name"
    )
    proposed: List[str] = []
    for name in result.get("names") or []:
        if not isinstance(name, str):
            continue
        name = name.strip().lower()
        if vocabulary.get(name) and name not in proposed:
            proposed.append(name)
    return proposed[:MAX_PROPOSALS]


def choose_proposed(text: str) -> str:
    """The exercise the athlete picks among the names proposed for `text`, on the spot: she
    has just typed, and nothing is named without her choice. Raises NotApplied otherwise."""
    if not text.strip():
        raise NotApplied("Nothing named.")
    try:
        proposed = propose(text)
    except Exception as e:
        raise NotApplied(f"Couldn't look up “{text}” ({e}). Nothing named.")
    if not proposed:
        raise NotApplied(f"No exercise TrainMate knows matches “{text}”. Nothing named.")
    choices = [Choice(name, name) for name in proposed]
    choices.append(Choice(NONE_OF_THESE, "none of these"))
    picked = runtime.prompt.choose(
        f"Which exercise is “{text}”?", choices, default=NONE_OF_THESE
    )
    if picked == NONE_OF_THESE:
        raise NotApplied("Nothing named.")
    return picked


SETS_FINAL_KIND = Kind(
    name=sets.SETS_FINAL, shape=QUESTION,
    wording=_sets_final_wording, companion_wording=_sets_final_companion,
    is_stale=_sets_final_stale, apply=_apply_sets_final, drop_label=_sets_final_drop,
    on_drop=_drop_sets_final,
)

SET_NAMES_KIND = Kind(
    name=sets.SET_NAMES, shape=QUESTION,
    wording=lambda item: _set_names_words(item, companion=False),
    companion_wording=lambda item: _set_names_words(item, companion=True),
    is_stale=_set_names_stale, apply=_apply_set_names, drop_label=LEAVE_UNNAMED,
)
