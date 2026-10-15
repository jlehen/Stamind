"""Which voice a CLI process speaks in: the one place STAMIND_RENDER is interpreted
(DESIGN_render_persona.md §2, §4).

A module of its own, not the package's `__init__`, so that importing a line builder does not
import the two renderers, whose expert half reaches into the commands (§7).
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
