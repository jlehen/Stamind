"""The voice a CLI process speaks in (DESIGN_render_persona.md).

STAMIND_RENDER picks one renderer at startup and `runtime.render` hands it out, the
way STAMIND_FRONTEND picks a prompt transport: a command says *what happened* and
never asks which persona heard it. `expert.py` is the terminal voice, `companion.py`
the simple bot's, and `session_lines.py` with `plan_lines.py` are the pure line
builders the companion voice — and `bot morning`, directly — is written from (§3, §7).

Command modules never import this package: they reach it through `runtime.render`,
whose builder defers the import (§7).
"""
import os
from typing import Optional

from stamind.cli.render.companion import CompanionRenderer
from stamind.cli.render.expert import ExpertRenderer


def make_renderer(render: Optional[str] = None):
    """The one place STAMIND_RENDER is interpreted (mirrors `prompt.make_prompt`)."""
    if render is None:
        render = os.environ.get("STAMIND_RENDER", "")
    if render.strip().lower() == "simple":
        return CompanionRenderer()
    return ExpertRenderer()
