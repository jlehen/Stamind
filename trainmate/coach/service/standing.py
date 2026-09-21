"""The sessions the athlete has already been told about.

It is Wednesday, and the commitment window runs to Friday. Thursday's ride is on the
athlete's calendar and in their week. A `workout generate` over the coming fortnight must
answer for Thursday rather than quietly rewrite it, so the week planner is shown the
sessions standing inside that window and answers `keep`, a rewrite, a `drop` or a move for
each. This file turns those answers into the list every later pass sees, into the slots
the run ends, and into the lines the preview shows
(DESIGN_plan_change_continuity.md §4.5, §5.5, §7).

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from typing import Any, Dict, List, Optional, Tuple

from trainmate.types import Workout
from trainmate.coach.proposals import StandingLine
from trainmate.coach.revisions import prescription_matches, replaces_source, rest_in_place_of
from trainmate.sports import canonical_sport
from trainmate.output import notice


# What a void says when nothing the week planner answered explains it: the second and later
# sessions on a date a rest constraint clears carry the constraint's own title, and
# everything else at least names who did it (DESIGN_plan_change_continuity.md §5.5).
REPLACED_DAY_REASON = "Your coach replaced this day."


class StandingMixin:
    @staticmethod
    def _standing_sessions(
        span_sessions: List[Workout], window_end: Optional[str]
    ) -> List[Workout]:
        """The sessions the week planner must answer for (§4.2): the ones inside the
        commitment window.

        They are already bounded by the span, because `span_sessions` is read from it — which
        is the second bound the intersection needs, or a forward-selected run would ask
        the week planner about days it cannot write and the preview would lie."""
        if window_end is None:
            return []
        chosen = [w for w in span_sessions if w['date'] <= window_end]
        return sorted(chosen, key=lambda w: (w['date'], canonical_sport(w['sport_type'])))

    @staticmethod
    def _dropped_rest(answer: Dict[str, Any], source: Workout) -> Dict[str, Any]:
        """A `drop` as the rest day that takes the session's place (§4.5/§5.4).

        There is one path through apply for every answer but `keep`, and a dropped ride
        leaves exactly what an adapted one does: one event on the day, now titled "Rest
        Day", with the ride underneath it in History and the coach's sentence on it."""
        rest = rest_in_place_of(
            source, str(answer.get('change_reason') or ''),
            f"{source['title']} cancelled by your coach.",
        )
        rest['replaces'] = {'date': source['date'], 'sport_type': source['sport_type']}
        return rest

    @classmethod
    def _resolve_standing(
        cls, workouts: List[Dict[str, Any]], standing_sessions: List[Workout],
        gen_start: str, gen_end: str
    ) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], str]]:
        """Maps the week planner's answers onto the standing sessions, so every pass after this one
        sees a uniform list of full sessions
        (DESIGN_plan_change_continuity.md §4.5, §7).

        `keep` becomes the session it names, `drop` becomes a rest day replacing it, and a
        full entry on a date whose only standing session is a rest day replaces that rest
        day whether the week planner said so or not. What an entry takes the place of travels on
        it as `replaces_slot`/`replaces_lineage`, which apply turns into a void plus an
        append on the same lineage. A standing session no answer names is kept.

        Returns the sessions and `{slot: reason}` for the standing sessions an answer ends
        without leaving a session in their place — the coach's own sentence, so the void
        the athlete meets says what the coach said (§5.5).
        """
        rest_sport = canonical_sport('rest')
        by_slot = {(w['date'], canonical_sport(w['sport_type'])): w for w in standing_sessions}
        per_date: Dict[str, List[Workout]] = {}
        for live in standing_sessions:
            per_date.setdefault(live['date'], []).append(live)
        # A rest day and a session on the same date cannot both be true, so the week planner is
        # not offered the choice: a full entry there replaces the rest day (§4.5).
        rest_only = {
            day: rows[0] for day, rows in per_date.items()
            if len(rows) == 1 and canonical_sport(rows[0]['sport_type']) == rest_sport
        }

        entries: List[Dict[str, Any]] = []
        for w in workouts:
            if not w.get('drop'):
                entries.append(w)
                continue
            slot = (w.get('date'), canonical_sport(w.get('sport_type', '')))
            source = by_slot.get(slot)
            if source is None or slot[1] == rest_sport:
                notice(
                    f"The coach dropped {w.get('sport_type', '')} on {w.get('date')}, "
                    f"but no session of yours stands there — ignoring it.",
                )
                continue
            entries.append(cls._dropped_rest(w, source))

        def source_of(entry: Dict[str, Any]) -> Optional[Tuple[str, str]]:
            """The standing slot an entry takes a session out of, or None."""
            slot = (entry.get('date'), canonical_sport(entry.get('sport_type', '')))
            replaces = entry.get('replaces')
            if isinstance(replaces, dict) and replaces.get('date'):
                return replaces_source(entry)
            rest = rest_only.get(entry.get('date'))
            if rest is None:
                return None
            rest_slot = (rest['date'], rest_sport)
            return None if rest_slot == slot else rest_slot

        # Read before any entry is resolved, so a destination is judged against what the
        # occupant's OWN answer does with it (§4.5).
        vacated = {
            source for source in
            (source_of(e) for e in entries if not e.get('keep'))
            if source is not None
        }
        written = {
            (w.get('date'), canonical_sport(w.get('sport_type', '')))
            for w in entries if not w.get('keep')
        }

        out: List[Dict[str, Any]] = []
        answered: set = set()        # standing slots an accepted entry has spoken for
        taken: set = set()           # destination slots an accepted entry has claimed
        void_reasons: Dict[Tuple[str, str], str] = {}

        def ends(source: Tuple[str, str], entry: Dict[str, Any]) -> None:
            """The entry cannot be written, but it still answered for its source: the
            session ends, and the coach's sentence goes on the void rather than the
            fallback (§5.5)."""
            void_reasons[source] = (
                str(entry.get('change_reason') or '').strip() or REPLACED_DAY_REASON
            )
            answered.add(source)

        for entry in entries:
            slot = (entry.get('date'), canonical_sport(entry.get('sport_type', '')))
            if entry.get('keep'):
                live = by_slot.get(slot)
                if live is None or slot in written or slot in taken:
                    continue
                out.append({**live, 'keep': True})
                answered.add(slot)
                taken.add(slot)
                continue
            source = source_of(entry)
            if slot in taken:
                notice(
                    f"Two sessions came back for {slot[0]} ({entry.get('sport_type', '')})"
                    f" — keeping the first and dropping the rest.",
                )
                # Two sessions on one date, both dropped: the second rest day has nowhere
                # to land, but the session it stood for is still gone.
                if source in by_slot and source not in answered:
                    ends(source, entry)
                continue
            if source is not None and source not in by_slot:
                notice(
                    f"The coach said this {entry.get('date')} session replaces one on "
                    f"{source[0]} that is not among the sessions it was shown — writing "
                    f"it where it stands and leaving that day alone.",
                )
                source = None
            if source is not None:
                if not (gen_start <= (entry.get('date') or '') <= gen_end):
                    notice(
                        f"The coach moved the {source[0]} session to "
                        f"{entry.get('date')}, outside the days this run writes — "
                        f"leaving it where it is.",
                    )
                    continue
                if source in answered:
                    notice(
                        f"Two answers came back for the {source[0]} session — keeping "
                        f"the first.",
                    )
                    continue
                if slot in by_slot and slot not in vacated:
                    notice(
                        f"The coach moved the {source[0]} session onto "
                        f"{entry.get('date')}, where a session it is keeping already "
                        f"stands — leaving both where they are.",
                    )
                    continue
                occupant = by_slot[source]
                entry = {
                    **entry,
                    'replaces_slot': (occupant['date'], occupant['sport_type']),
                    'replaces_lineage': occupant['id'],
                }
                answered.add(source)
            elif slot in by_slot:
                answered.add(slot)
            out.append(entry)
            taken.add(slot)

        # A rest day and a session on the same date cannot both be true (§4.5). A drop's
        # rest day is the one that can collide — another answer may put work on the day it
        # emptied — and the work wins; the coach's sentence travels to the void the drop
        # leaves behind, which is what the athlete then meets as a `[Cancelled]` marker.
        worked_dates = {
            w['date'] for w in out
            if canonical_sport(w.get('sport_type', '')) != rest_sport
        }
        standing_only: List[Dict[str, Any]] = []
        for entry in out:
            replaced = entry.get('replaces_slot')
            if (replaced and entry['date'] in worked_dates
                    and canonical_sport(entry.get('sport_type', '')) == rest_sport):
                ends((replaced[0], canonical_sport(replaced[1])), entry)
                continue
            standing_only.append(entry)
        out = standing_only

        # Silence is how a JSON-mode model fails, and a cancellation has to be said (§4.5).
        for slot, live in by_slot.items():
            if slot in answered:
                continue
            out.append({**live, 'keep': True, 'unmentioned': True})
        return out, void_reasons

    @staticmethod
    def _generate_voids(
        workouts: List[Dict[str, Any]], span_sessions: List[Workout],
        void_reasons: Dict[Tuple[str, str], str]
    ) -> Tuple[Tuple[str, str, str], ...]:
        """Every slot this run ends, with the reason it will carry (§5.5).

        Decided here rather than inside apply so the preview reports the removals that
        will actually happen, including the ones no answer explains."""
        final = {(w['date'], canonical_sport(w['sport_type'])) for w in workouts}
        kept = {
            (w['date'], canonical_sport(w['sport_type']))
            for w in workouts if w.get('keep')
        }
        voids: List[Tuple[str, str, str]] = []
        seen: set = set()
        for w in workouts:
            replaced = w.get('replaces_slot')
            if not replaced:
                continue
            slot = (replaced[0], canonical_sport(replaced[1]))
            if slot in seen:
                continue
            seen.add(slot)
            reason = str(w.get('change_reason') or '').strip() or REPLACED_DAY_REASON
            voids.append((replaced[0], replaced[1], reason))
        for live in span_sessions:
            slot = (live['date'], canonical_sport(live['sport_type']))
            if slot in seen or slot in kept:
                continue
            explicit = void_reasons.get(slot)
            # Written over where it stands, and superseded by the append: a void is only
            # needed when the removal has to leave a trace of its own — a session an answer
            # ended before something else took its slot (§5.1).
            if slot in final and explicit is None:
                continue
            seen.add(slot)
            voids.append((
                live['date'], live['sport_type'], explicit or REPLACED_DAY_REASON,
            ))
        return tuple(voids)

    @staticmethod
    def _standing_line(
        live: Workout, outcome: str, becomes: str = "", reason: str = "",
        mentioned: bool = True,
    ) -> StandingLine:
        """One report row about `live`, whatever this run decided for it."""
        return StandingLine(
            date=live['date'], sport_type=live['sport_type'], title=live['title'],
            duration_minutes=live.get('duration_minutes'), outcome=outcome,
            becomes=becomes, reason=reason, mentioned=mentioned,
        )

    @staticmethod
    def _becomes(entry: Dict[str, Any], live: Workout) -> Tuple[str, str]:
        """`(outcome, becomes)` for one standing session the run rewrites (§4.5)."""
        if entry.get('date') != live['date']:
            return 'moved', entry['date']
        duration = entry.get('duration_minutes')
        title = entry.get('title') or ''
        becomes = f"{title} {duration}m" if duration else title
        return 'revised', becomes

    @classmethod
    def _standing_lines(
        cls, workouts: List[Dict[str, Any]], standing_sessions: List[Workout],
        voids: Tuple[Tuple[str, str, str], ...]
    ) -> Tuple[StandingLine, ...]:
        """The §4.5 report, built from what apply will write rather than from what the
        coach answered: the no-op rule silently suppresses a revision whose prescription
        did not move, and the deterministic passes remove sessions no answer mentions."""
        by_slot = {(w['date'], canonical_sport(w['sport_type'])): w for w in workouts}
        by_source: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for w in workouts:
            replaced = w.get('replaces_slot')
            if replaced:
                by_source[(replaced[0], canonical_sport(replaced[1]))] = w
        reasons = {(d, canonical_sport(sp)): r for (d, sp, r) in voids}

        lines: List[StandingLine] = []
        for live in standing_sessions:
            slot = (live['date'], canonical_sport(live['sport_type']))
            # What this session became, wherever it went: a move, a sport change and the
            # rest day of a drop all carry it out of its slot.
            target = by_source.get(slot)
            entry = by_slot.get(slot)
            # An entry that takes another session's place is a different session arriving,
            # not this one continuing — so this one was displaced, not revised.
            if target is None and entry is not None and not entry.get('replaces_slot'):
                if entry.get('keep') or prescription_matches(entry, live):
                    lines.append(cls._standing_line(
                        live, 'kept', mentioned=not entry.get('unmentioned')
                    ))
                    continue
                target = entry
            if target is None:
                lines.append(cls._standing_line(
                    live, 'cancelled', reason=reasons.get(slot, '')
                ))
                continue
            outcome, becomes = cls._becomes(target, live)
            lines.append(cls._standing_line(
                live, outcome, becomes=becomes,
                reason=str(target.get('change_reason') or '').strip(),
            ))
        return tuple(lines)
