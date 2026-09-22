"""Sports-science coaching layer.

Each submodule is imported by its own path — this package re-exports nothing, so
``from stamind.coach import honoring`` costs the one module and not the whole coach
(AGENTS.md, Code style):

  - ``formatting`` — pure prompt-formatting helpers (no I/O, no LLM).
  - ``engine``     — ``CoachEngine``: prompt construction, hashing, and LLM calls. Holds
                     the ``openrouter_client`` binding, so the patch target for the model
                     call is ``stamind.coach.engine.openrouter_client``.
  - ``service``    — ``CoachService`` and the ``coach_service`` singleton: data I/O,
                     caching, orchestration. It holds no handles of its own; the comments
                     in ``service/__init__.py`` say which and why.
  - ``honoring``   — whether the schedule reflects a constraint yet, asked by the CLI.
  - ``proposals``  — the frozen records the coach hands the CLI before the athlete has
                     accepted anything, and ``revisions`` — the pure helpers that fill
                     one in.

The ``config`` singleton is ``stamind.config.config``, the one object every submodule
imports, so an in-place mutation of ``stamind.config.config.data`` is visible
everywhere.
"""
