"""Which layer is allowed to load which.

A layer is broken by one import line in one file, and nothing notices: the suite stays
green because everything still works, only slower and more tangled. So each rule is a
test that imports a module in a fresh interpreter and reads `sys.modules` afterwards —
what actually got loaded, not what the file says it imports.

Every rule is keyed on a module-name prefix, never on a list of files, so a new file
under a package is covered the day it is written (REORG_execution.md §5.2).
"""
import glob
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modules_loaded_by(import_lines: str, prefixes: tuple) -> list:
    """The modules matching `prefixes` that a fresh interpreter has loaded after running
    `import_lines`. Raises if the probe itself fails."""
    probe = (
        f"{import_lines}\n"
        "import sys\n"
        f"hit = sorted(m for m in sys.modules if m.startswith({prefixes!r}))\n"
        "print('LOADED:' + repr(hit))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("LOADED:")][-1]
    return eval(line[len("LOADED:"):])       # a repr of a list of strings, from our probe


class TestAnalyticsIsPure(unittest.TestCase):
    """`trainmate/analytics/` is training maths over rows it is handed.

    Importing any of it must not pull in the storage layer. The rule is what lets the
    coach, the CLI and the web app share one load model without three of them paying for
    a database package they are not using (REORG_code_layout.md §4.1).

    A module here may still take a database handle as an argument — `adherence_window`
    does. It is being handed one that someone else built; that is not the same as
    importing `trainmate.db`.
    """

    def test_no_analytics_module_loads_the_database_package(self):
        offenders = {}
        for path in sorted(glob.glob(os.path.join(REPO, "trainmate", "analytics", "*.py"))):
            name = os.path.basename(path)[:-3]
            module = "trainmate.analytics" if name == "__init__" else f"trainmate.analytics.{name}"
            loaded = _modules_loaded_by(f"import {module}", ("trainmate.db",))
            if loaded:
                offenders[module] = loaded
        self.assertEqual(
            offenders, {},
            "these analytics modules load the storage layer; take the rows as an "
            f"argument instead of importing trainmate.db: {offenders}",
        )


class TestTheWebAppIsAReader(unittest.TestCase):
    """`trainmate_web` serves the dashboard and writes nothing.

    That is a claim about capability, not about intent: a reader that has imported the
    coach service or the Calendar client is one call away from writing, and an operator
    reading the dashboard has not asked for either. It also means the web process needs
    no service-account credentials and no OpenRouter key to start.

    This replaced a grep over the web file's own text, which kept passing while the
    import happened one module deeper — `cli/workouts/_helpers` reached the CLI package,
    and the CLI package reached everything (REORG_code_layout.md §4.3).
    """

    FORBIDDEN = (
        "trainmate.cli",              # a front-end; the web app is another one
        "trainmate.coach",            # the model call and everything it orchestrates
        "trainmate.openrouter",       # the model client itself
        "trainmate.gcal",             # writes events, and reads the credentials file
        "googleapiclient",
    )

    def test_importing_the_web_app_loads_no_writer(self):
        loaded = _modules_loaded_by("import trainmate_web", self.FORBIDDEN)
        self.assertEqual(
            loaded, [],
            "the web app is read-only, so importing it must not load these; follow the "
            f"chain from trainmate_web's own imports: {loaded}",
        )


class TestTheChatPackageNeedsNoTelegram(unittest.TestCase):
    """`trainmate/chat/` is the Telegram front-end's own code, apart from the process.

    `chat/telegram_api.py` is the only module that names `python-telegram-bot`, and it
    imports the library inside each function rather than at module scope, so importing
    anything under `trainmate/chat/` loads none of it. That is what makes the whole
    front-end — the routing tables, the keyboards, the scheduler and `ChatBot` itself —
    unit-testable without the library, and what lets `tm bot route` read the router's
    intent table out of `chat/routing.py` without a chat front-end turning up on a
    command line.
    """

    def test_no_chat_module_loads_the_telegram_library(self):
        offenders = {}
        for path in sorted(glob.glob(os.path.join(REPO, "trainmate", "chat", "*.py"))):
            name = os.path.basename(path)[:-3]
            module = "trainmate.chat" if name == "__init__" else f"trainmate.chat.{name}"
            loaded = _modules_loaded_by(f"import {module}", ("telegram",))
            if loaded:
                offenders[module] = loaded
        self.assertEqual(
            offenders, {},
            "these chat modules load python-telegram-bot at import; the library is named "
            "in chat/telegram_api.py alone, inside the function that needs it, not here: "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
