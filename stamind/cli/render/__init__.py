"""The voice a CLI process speaks in (DESIGN_render_persona.md).

STAMIND_RENDER picks one renderer at startup and `runtime.render` hands it out, the
way STAMIND_FRONTEND picks a prompt transport: a command says *what happened* and
never asks which persona heard it. `persona.py` reads STAMIND_RENDER, `expert.py` is the
terminal voice, `companion.py` the bot's, and `session_lines.py` with `plan_lines.py` are
the pure line builders the companion voice — and `bot morning`, directly — is written from
(§3, §7).

Command modules never import this package: they reach it through `runtime.render`,
whose builder defers the import (§7).
"""
