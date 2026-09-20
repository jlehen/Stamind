from typing import Dict, List, Optional, Tuple
from trainmate.types import Mesocycle


class MesocyclesMixin:
    """Reading the mesocycles of a plan, and which one covers a given date.

    Three readers answer that last question, and they differ only in what they do when
    no mesocycle covers the date: `_get_covering_mesocycles` and `get_covering_mesocycle`
    return nothing, `get_governing_mesocycles` falls back to the nearest one, and
    `get_active_mesocycle` falls back to the next future one and then to the first of all.
    The rows themselves are written by `save_macrocycle` in `db/periodization.py`.
    """

    def get_mesocycles_for_macrocycle(self, macrocycle_id: int) -> List[Mesocycle]:
        """Fetches all mesocycles in chronological order belonging to a macrocycle."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM mesocycles WHERE macrocycle_id = ? ORDER BY start_date ASC",
                (macrocycle_id,)
            )
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    def _get_covering_mesocycles(
        self, start_date: str, end_date: Optional[str] = None,
        prefer_macro_id: Optional[int] = None
    ) -> Tuple[List[Mesocycle], List[int]]:
        """The mesocycles that ACTUALLY overlap a window — or none — plus the macrocycle IDs
        dropped as conflicts. The strict half of `get_governing_mesocycles`, its one
        caller: an empty answer means no mesocycle covers any of these days, which is what
        lets the governing reader fall back only when it should.

        Sequential plans both survive — a long span legitimately crosses from one goal's
        last mesocycle into the next goal's first — but two plans covering the *same* dates
        cannot both be followed, so the most recently created wins, the same tiebreak
        get_periodization_ids_for_date makes per day. `prefer_macro_id` settles that
        contest by hand instead.

        `end_date=None` means no upper bound — "every mesocycle from here to the plan's end",
        the form `get_constraints` already takes, so no caller has to invent a far-future
        date to stand in for one.
        """
        clauses = ["m.end_date >= ?"]
        params: List[str] = [start_date]
        if end_date is not None:
            clauses.append("m.start_date <= ?")
            params.append(end_date)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT m.* FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                JOIN objectives o ON mac.objective_id = o.id
                WHERE o.status = 'active' AND COALESCE(mac.status, 'active') = 'active'
                  AND {' AND '.join(clauses)}
                ORDER BY m.start_date ASC, m.id ASC
            """, params)
            mesos = [dict(row) for row in cursor.fetchall()]
        if not mesos:
            return [], []

        spans: Dict[int, Tuple[str, str]] = {}
        for m in mesos:
            mid = m['macrocycle_id']
            start, end = spans.get(mid, (m['start_date'], m['end_date']))
            spans[mid] = (min(start, m['start_date']), max(end, m['end_date']))

        kept: List[int] = []
        dropped: List[int] = []
        # Newest plan first, unless one was named; a plan is dropped only when it fights
        # an already-kept plan for the same days.
        for mid in sorted(spans, key=lambda i: (i == prefer_macro_id, i), reverse=True):
            start, end = spans[mid]
            if any(start <= spans[k][1] and end >= spans[k][0] for k in kept):
                dropped.append(mid)
            else:
                kept.append(mid)
        return [m for m in mesos if m['macrocycle_id'] in kept], sorted(dropped)

    def get_governing_mesocycles(
        self, start_date: str, end_date: Optional[str] = None,
        prefer_macro_id: Optional[int] = None
    ) -> Tuple[List[Mesocycle], List[int]]:
        """The mesocycles that govern a window, plus the macrocycle IDs dropped as
        conflicts — the one window reader (DESIGN_cli_selectors.md §8).

        Overlap and arbitration are `_get_covering_mesocycles`'s: whole plans survive or
        drop, the most recently created wins, `prefer_macro_id` overrides. When nothing
        overlaps at all, answers with get_active_mesocycle's nearest mesocycle instead — so
        a plan that starts after the window still answers, and an empty result means
        there is genuinely no plan. A caller that treats the answer as covering a *date*
        wants the strict single-date reader, `get_covering_mesocycle`."""
        mesos, dropped = self._get_covering_mesocycles(
            start_date, end_date, prefer_macro_id
        )
        if mesos:
            return mesos, dropped
        nearest = self.get_active_mesocycle(start_date)
        return ([nearest] if nearest else []), []

    def get_mesocycle_ranges(self, start_date: str, end_date: str) -> List[Tuple[str, str]]:
        """Returns the (start_date, end_date) spans of all mesocycles overlapping the
        given window, across every objective regardless of status.

        Used to decide whether a date fell inside *any* planned mesocycle: an activity on a
        covered date with no matching workout is a genuine deviation, whereas one outside
        all coverage is just history the plan never governed (e.g. before tool adoption,
        or an unplanned off-season stretch). Objective status is intentionally not
        filtered — a since-completed objective still planned its dates — but superseded
        plan *versions* are excluded so an old version's ranges don't double-count the
        same dates as the active one (see DESIGN_plan_rollback.md)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.start_date, m.end_date FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                WHERE COALESCE(mac.status, 'active') = 'active'
                  AND m.start_date <= ? AND m.end_date >= ?
                ORDER BY m.start_date ASC
            """, (end_date, start_date))
            return [(row['start_date'], row['end_date']) for row in cursor.fetchall()]

    def get_periodization_ids_for_date(
        self, date: str
    ) -> Optional[Tuple[int, int, int]]:
        """Resolves the (objective_id, macrocycle_id, mesocycle_id) covering a date.

        Returns the mesocycle whose span contains the given date, along with its
        parent macrocycle and objective ids. When overlapping mesocycles exist across
        objectives, the most recently created macrocycle wins. Returns None if no
        mesocycle covers the date. Used to stamp calendar events with traceability
        back to the plan that produced them.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mac.objective_id AS objective_id,
                       m.macrocycle_id AS macrocycle_id,
                       m.id AS mesocycle_id
                FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                WHERE COALESCE(mac.status, 'active') = 'active'
                  AND m.start_date <= ? AND m.end_date >= ?
                ORDER BY mac.id DESC, m.start_date ASC
                LIMIT 1
            """, (date, date))
            row = cursor.fetchone()
            if not row:
                return None
            return (
                row['objective_id'],
                row['macrocycle_id'],
                row['mesocycle_id'],
            )

    def get_mesocycle(self, mesocycle_id: int) -> Optional[Mesocycle]:
        """Fetches a specific mesocycle by its unique ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mesocycles WHERE id = ?", (mesocycle_id,))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def get_covering_mesocycle(self, target_date: str) -> Optional[Mesocycle]:
        """The active mesocycle that actually CONTAINS this date, or None. The strict
        reader: what every caller wants that goes on to read the answer's dates as
        covering the target. Only considers active objectives. When overlapping plans
        both contain the date, the most recently created wins — the same tiebreak
        get_periodization_ids_for_date makes, so no two readers name different mesocycles
        for one day."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.* FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                JOIN objectives o ON mac.objective_id = o.id
                WHERE o.status = 'active' AND COALESCE(mac.status, 'active') = 'active'
                  AND m.start_date <= ? AND m.end_date >= ?
                ORDER BY mac.id DESC, m.start_date ASC LIMIT 1
            """, (target_date, target_date))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def get_active_mesocycle(self, target_date: str) -> Optional[Mesocycle]:
        """`get_covering_mesocycle`, falling back to the next future mesocycle, or the
        absolute first one, when none contains the date — the mesocycle a command should act
        RELATIVE to, not necessarily one containing the date. A caller that reads the
        answer's dates as covering the target wants the strict reader instead."""
        covering = self.get_covering_mesocycle(target_date)
        if covering:
            return covering
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Fallback 1: first mesocycle that ends in the future
            cursor.execute("""
                SELECT m.* FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                JOIN objectives o ON mac.objective_id = o.id
                WHERE o.status = 'active' AND COALESCE(mac.status, 'active') = 'active'
                  AND m.end_date >= ?
                ORDER BY m.start_date ASC, mac.id DESC LIMIT 1
            """, (target_date,))
            row = cursor.fetchone()
            if row: return dict(row) # type: ignore

            # Fallback 2: absolute first mesocycle
            cursor.execute("""
                SELECT m.* FROM mesocycles m
                JOIN macrocycles mac ON m.macrocycle_id = mac.id
                JOIN objectives o ON mac.objective_id = o.id
                WHERE o.status = 'active' AND COALESCE(mac.status, 'active') = 'active'
                ORDER BY m.start_date ASC, mac.id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None # type: ignore
