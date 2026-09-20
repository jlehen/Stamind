"""Strength tracking (DESIGN_strength_tracking.md): what the athlete lifted, and what the
next session asks them to lift.

- `vocabulary.py` — the exercise names TrainMate knows, read from `exercises.tsv`.
- `sets.py` — a strength activity's sets, read from Garmin once and then frozen.
- `questions.py` — the two questions the athlete is queued: are these sets final, and what
  was this group the watch could not name.
- `history.py` — the recent lifting written out for the strength planner to read.
- `prescription.py` — a strength session's description, built from its prescribed sets.
- `planner.py` — the strength planner: the sessions the call is about, the call, and what is
  done with the answers.
- `planner_prompt.py` — what that call tells the model, and the checks on what comes back.
  `progression.md` beside it is the shipped science only this call reads.
"""
