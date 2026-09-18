"""What a feature brings to the athlete queue, and how it queues an item
(DESIGN_athlete_queue.md §8).

Kept apart from `trainmate/athlete_queue.py`, which holds the list of kinds: a feature's
answers queue items of their own, so the feature imports this module and the queue
imports the feature.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union

from trainmate import clock, runtime

QUESTION = "question"
MESSAGE = "message"

# How an item closed (§4).
ANSWERED = "answered"
DROPPED = "dropped"
STALE = "stale"


@dataclass(frozen=True)
class Kind:
    """What a feature brings to the queue (§8).

    `apply` gets the item, the position of the chosen answer and the typed text when that
    answer asks for one (an answer with an `ask` key), and returns the line confirming it.
    It raises `NotApplied` when the answer could not be applied, and the item waits (§4). A
    question without a `drop_label` offers no drop: every one of its answers settles it.

    `drop_label` is one wording, or a function of the item when what the drop costs depends
    on what was asked — "the watch's names won't count" only where the watch guessed one
    (DESIGN_strength_tracking.md §7)."""
    name: str
    shape: str
    wording: Callable[[Dict[str, Any]], str]
    companion_wording: Callable[[Dict[str, Any]], str]
    is_stale: Callable[[Dict[str, Any]], bool]
    apply: Callable[[Dict[str, Any], int, Optional[str]], Optional[str]]
    drop_label: Optional[Union[str, Callable[[Dict[str, Any]], str]]] = None
    # What the drop itself writes, where dropping a question settles something in the
    # feature as well as in the queue — "leave it as it is" freezes an activity's sets as
    # they were first read (DESIGN_strength_tracking.md §7).
    on_drop: Optional[Callable[[Dict[str, Any]], None]] = None


class NotApplied(Exception):
    """An answer its kind could not apply: Garmin out of reach, or none of the proposed
    names chosen. The message is the line shown in place of a confirmation (§4)."""


def queue(kind: str, subject: str, payload: Dict[str, Any]) -> Optional[int]:
    """Queues an item once per kind and subject, and returns its id (§3).

    Dated by the command that queues it, so an item the morning push queues while it runs
    belongs to the walk the push opens at its end (§4)."""
    return runtime.db.queue_item(kind, subject, payload, clock.command_start())
