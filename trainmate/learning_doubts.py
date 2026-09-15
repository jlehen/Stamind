"""The coach asks the athlete before it leans less on something it learned
(DESIGN_learning_doubt_nudge.md).

The `learning` queue kind, and what every `data reflect` and `data bootstrap` run does with
the doubts it leaves pending: one question each while the questions are on, or the step
"Not really" would take while they are off (§3.2, §3.4, §5).
"""
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from trainmate import clock, runtime, settings
from trainmate.db.learnings import RETIRE_PROPOSAL
from trainmate.db.queue import queue_stamp
from trainmate.queue_kind import QUESTION, STALE, Kind, queue
from trainmate.util import step

KIND = "learning"
STILL_FITS = 0
ANSWERS = ({"label": "still fits"}, {"label": "not really"})
# Said in place of what the coach saw, when reflect gave no reason (§4).
LESS_SURE = "Lately I'm less sure."

# `CoachService.learning_question`: the statement, and what the coach saw or None.
Sentences = Callable[[Dict[str, Any], List[Dict[str, Any]]], Tuple[str, Optional[str]]]


def _retires(payload: Dict[str, Any]) -> bool:
    return payload["step"] == RETIRE_PROPOSAL


def _wording(item: Dict[str, Any]) -> str:
    """The learning as the coach stores it, the step, the reasons and what each answer does
    (§8). The first line is what `queue` lists."""
    payload = item["payload"]
    learning_id, level = payload["learning_id"], payload["level"]
    lines = [
        f"Recent weeks contradict learning #{learning_id}: {level} → {payload['step']}.",
        f"[{learning_id}|{payload['sports']}|{level}] {payload['text']}",
    ]
    for row in payload["reasons"]:
        label = "Week" if len(row["weeks"]) == 1 else "Weeks"
        lines.append(f"{label} of {', '.join(row['weeks'])}: {row['reason']}")
    effect = "archives it" if _retires(payload) else "demotes it"
    lines.append(f"Still fits keeps it and overrules those weeks. Not really {effect}.")
    return "\n".join(lines)


def _companion_wording(item: Dict[str, Any]) -> str:
    """The coach's two sentences inside fixed words, with no id and no tier (§4)."""
    payload = item["payload"]
    effect = "I'll set it aside." if _retires(payload) else "I'll lean on it less."
    return (
        "Something I've been assuming about you — tell me if it still fits: "
        f"“{payload['statement']}” {payload['saw'] or LESS_SURE} "
        f"If it doesn't fit any more, or you're not sure, {effect}"
    )


def _is_stale(item: Dict[str, Any]) -> bool:
    """Settled once the questions are off, the learning is gone, archived or dormant, or it
    no longer has the proposal the question was about (§5)."""
    if not settings.learning_questions():
        return True
    payload = item["payload"]
    learning = runtime.db.get_learning(payload["learning_id"])
    if learning is None or learning["archived"] or learning["dormant"]:
        return True
    return learning["proposed_confidence"] != payload["step"]


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> None:
    """Still fits keeps the learning as `learnings keep` does, Not really demotes it as
    `learnings demote` does, and the renderer says what happened (§4)."""
    learning_id = item["payload"]["learning_id"]
    if index == STILL_FITS:
        runtime.db.keep_learning(learning_id)
        runtime.render.learning_kept(runtime.db.get_learning(learning_id))
        return None
    runtime.render.learning_demoted(learning_id, runtime.db.demote_learning(learning_id))
    return None


# No drop: every answer settles the doubt, and "Not now" already puts it off (§4).
LEARNING_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_wording, companion_wording=_companion_wording,
    is_stale=_is_stale, apply=_apply,
)


def _still_waiting() -> Set[int]:
    """The learnings a waiting question is about, hidden ones included. Each question runs
    its check first, and a stale one is closed (§5)."""
    learning_ids: Set[int] = set()
    for item in runtime.db.waiting_queue_items():
        if item["kind"] != KIND:
            continue
        if _is_stale(item):
            runtime.db.close_queue_item(item["id"], STALE, clock.now())
            continue
        learning_ids.add(item["payload"]["learning_id"])
    return learning_ids


def contradiction_reasons(learning_id: int) -> List[Dict[str, Any]]:
    """What reflect said went against a learning, each reason once with the contradicting
    weeks it was filed for: one `contradict` op citing two weeks stores its reason on both
    (§4)."""
    weeks_by_reason: Dict[str, List[str]] = {}
    for row in runtime.db.get_learning_evidence(learning_id):
        if row["polarity"] < 0 and row["reason"]:
            weeks_by_reason.setdefault(row["reason"], []).append(row["week_commencing"])
    return [{"weeks": weeks, "reason": reason} for reason, weeks in weeks_by_reason.items()]


def _ask(learning: Dict[str, Any], sentences: Sentences) -> None:
    """Queues the question about one learning, written complete. A failed sentence call
    queues nothing, and the next run asks again (§4)."""
    reasons = contradiction_reasons(learning["id"])
    try:
        statement, saw = sentences(learning, reasons)
    except Exception as e:
        step(f"Couldn't word the question about learning #{learning['id']} ({e}); "
             "the next reflect run asks again.")
        return
    # The time makes a later doubt about the same learning a new subject (§5).
    subject = f"{learning['id']}@{queue_stamp(clock.command_start())}"
    queue(KIND, subject, {
        "learning_id": learning["id"],
        "step": learning["proposed_confidence"],
        "level": learning["confidence"],
        "sports": learning.get("sports") or "general",
        "text": learning["text"],
        "reasons": reasons,
        "statement": statement,
        "saw": saw,
        "answers": list(ANSWERS),
    })


def settle_doubts(sentences: Sentences) -> None:
    """What a reflect or bootstrap run does with the pending proposals, after the staleness
    steps: one question for each learning that is not dormant and has none waiting (§3.2,
    §5), or, with the questions switched off, the step "Not really" would take (§3.4)."""
    waiting = _still_waiting()
    asking = settings.learning_questions()
    for learning in runtime.db.get_learnings():
        if not learning["proposed_confidence"] or learning["archived"]:
            continue
        if not asking:
            runtime.db.demote_learning(learning["id"])
            continue
        if learning["dormant"] or learning["id"] in waiting:
            continue
        _ask(learning, sentences)
