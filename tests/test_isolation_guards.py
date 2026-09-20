"""The suite-wide isolation guards must actually fire.

Both guards installed in tests/__init__.py are backstops for seams that fail silently:
a handle rebinding that misses a site would otherwise read the athlete's real training
data, and a live network call would hit Garmin/OpenRouter for real. A guard that stopped
working would be invisible, so it is asserted here rather than trusted.

The `patch("trainmate…")` targets are checked here for the same reason: a target that has
stopped pointing at anything is a stub that no longer stubs.
"""
import ast
import glob
import importlib
import os
import socket
import sqlite3
import tempfile
import unittest

# The guards this file asserts on are installed by `tests/__init__.py`, and `unittest
# discover -s tests` imports the modules under `tests/` without importing the package
# itself. Every other module gets it for free through `from tests import test_db_path`;
# this one has no database to name, so it says so outright rather than run against guards
# that were never installed.
import tests        # noqa: F401

PRODUCTION_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trainmate.db")

_UNSET = object()   # "nothing was bound", as opposed to "bound to None"


class TestProductionDatabaseIsUnreachable(unittest.TestCase):
    def test_opening_the_real_database_raises(self):
        with self.assertRaises(RuntimeError) as caught:
            sqlite3.connect(PRODUCTION_DB)
        self.assertIn("must not open the production database", str(caught.exception))

    def test_the_relative_path_is_caught_too(self):
        """The guard compares absolute paths, so a relative spelling is the same file."""
        cwd = os.getcwd()
        os.chdir(os.path.dirname(PRODUCTION_DB))
        try:
            with self.assertRaises(RuntimeError):
                sqlite3.connect("trainmate.db")
        finally:
            os.chdir(cwd)

    def test_other_databases_still_open_normally(self):
        path = os.path.join(tempfile.mkdtemp(), "scratch.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.close()
        self.assertTrue(os.path.exists(path))


class TestSavingTheHandleDoesNotBuildIt(unittest.TestCase):
    """`helpers.restore_db_handles` is what a module calls before binding its own
    Database. Remembering the handle must not *create* one — reading `runtime.db` as an
    attribute resolves a module `__getattr__` that builds the real database against the
    production file, and the guard above then refuses it. Two modules wrote that by hand
    and both hit it, but only when run alone: inside the full suite an earlier module had
    already bound a handle, so the read found one cached.
    """

    def setUp(self):
        from trainmate import runtime
        self.modules = (runtime,)
        # Whatever the suite has bound so far goes back untouched, however this ends.
        saved = [(m, vars(m).get("db", _UNSET)) for m in self.modules]

        def _put_back():
            for module, previous in saved:
                if previous is _UNSET:
                    vars(module).pop("db", None)
                else:
                    module.db = previous
        self.addCleanup(_put_back)
        for module in self.modules:
            vars(module).pop("db", None)

    def test_remembering_an_unbound_handle_builds_nothing(self):
        from tests.helpers import restore_db_handles
        restore_db_handles(unittest.TestCase())      # would raise if it built one
        for module in self.modules:
            self.assertNotIn("db", vars(module), module.__name__)

    def test_an_unbound_handle_is_restored_to_absent(self):
        """Not to some value: leaving a concrete singleton where the lazy accessor was
        hands the next module a stale database instead of one it can still bind."""
        from tests.helpers import restore_db_handles
        borrower = unittest.TestCase()
        restore_db_handles(borrower)
        for module in self.modules:
            module.db = "a handle this test bound"
        borrower.doCleanups()
        for module in self.modules:
            self.assertNotIn("db", vars(module), module.__name__)


class TestNetworkIsUnreachable(unittest.TestCase):
    def test_remote_connections_raise(self):
        with self.assertRaises(RuntimeError) as caught:
            socket.socket().connect(("garmin.example.com", 443))
        self.assertIn("must not reach the network", str(caught.exception))


def _dirname_depth(node) -> int:
    """How many `os.path.dirname` calls wrap `__file__`, or 0 if this is not that shape.

    One is the `tests/` directory itself; two is the repository root, which is how
    PRODUCTION_DB above legitimately names the athlete's database.
    """
    depth = 0
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "dirname" and node.args:
        depth += 1
        node = node.args[0]
    if isinstance(node, ast.Name) and node.id == "__file__":
        return depth
    return 0


class TestTestDatabasesStayOutOfTheTestsDirectory(unittest.TestCase):
    """A module's SQLite file belongs in this process's own directory, via
    `tests.test_db_path` — never beside the tests.

    Two concurrent runs used to destroy each other: the files sat in `tests/` and the
    exit sweep removed every `*.db` it found there, including the one another process
    was still writing. Keyed on the shape that caused it rather than on a list of
    modules, so a file written tomorrow is covered tomorrow.
    """

    def test_no_module_joins_a_database_name_onto_the_tests_directory(self):
        offenders = []
        for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))):
            with open(path) as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                names_a_db = any(
                    isinstance(arg, ast.Constant) and str(arg.value).endswith(".db")
                    for arg in node.args
                )
                if not names_a_db:
                    continue
                if any(_dirname_depth(arg) == 1 for arg in node.args):
                    offenders.append(f"{os.path.basename(path)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "these build a database path inside tests/; use tests.test_db_path() so "
            f"concurrent runs cannot delete each other's files: {offenders}",
        )


def _called_name(node: ast.Call) -> str:
    """The bare name a call uses, so `patch(...)` and `mock.patch(...)` read the same."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _says_create(node: ast.Call) -> bool:
    """`create=True` tells mock the attribute may not exist, so it is not a stale target."""
    return any(
        kw.arg == "create" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.keywords
    )


def _loop_strings(node: ast.For) -> dict:
    """`{name: [string, …]}` for a `for` over a literal tuple or list of strings, else {}.

    Two tests write their targets that way — a loop over three module paths, and a loop
    over two attribute names fed into an f-string. A target the collector cannot read is a
    seam the gate cannot guard, and one of those four is `generate.ensure_recent_data`,
    which REORG_execution.md §9 calls the worst case.
    """
    if not isinstance(node.target, ast.Name) or not isinstance(node.iter, (ast.Tuple, ast.List)):
        return {}
    items = node.iter.elts
    values = [e.value for e in items
              if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(values) != len(items):
        return {}
    return {node.target.id: values}


def _possible_strings(node, bound: dict) -> list:
    """Every string `node` can be at run time: a literal, a name a `for` above it binds, or
    an f-string built from those. Empty when it cannot be read from the source alone."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return list(bound.get(node.id, ()))
    if not isinstance(node, ast.JoinedStr):
        return []
    built = [""]
    for piece in node.values:
        if isinstance(piece, ast.FormattedValue):
            options = _possible_strings(piece.value, bound)
        else:
            options = _possible_strings(piece, bound)
        if not options:
            return []
        built = [prefix + option for prefix in built for option in options]
    return built


def _collect(node, bound: dict, where: str, found: list) -> None:
    """Walk `node`, carrying the loop-bound names down into each `for` body so a target
    built from a loop variable is read with that loop's own values and no other's."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call) and child.args and _called_name(child) == "patch" \
                and not _says_create(child):
            for target in _possible_strings(child.args[0], bound):
                if target.startswith("trainmate."):
                    found.append((target, f"{where}:{child.lineno}"))
        inner = bound
        if isinstance(child, ast.For):
            inner = {**bound, **_loop_strings(child)}
        _collect(child, inner, where, found)


def _patch_targets():
    """Every `patch("trainmate…")` target in tests/, as (target, "file:line") pairs."""
    found = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "**", "*.py"),
                                 recursive=True)):
        with open(path) as handle:
            tree = ast.parse(handle.read())
        _collect(tree, {}, os.path.basename(path), found)
    return found


def _walk_to_the_owner(target: str):
    """Import and walk `target` the way `mock.patch` does, stopping one name short.

    Returns the object the last name hangs off, and that last name. The module half is
    imported, then each remaining name is read as an attribute — importing it as a
    submodule when the read fails, which is how a package reaches a module nothing has
    imported yet.
    """
    module_path, _, attribute = target.rpartition(".")
    names = module_path.split(".")
    owner = importlib.import_module(names[0])
    walked = names[0]
    for name in names[1:]:
        walked += "." + name
        if not _has(owner, name):
            importlib.import_module(walked)
        owner = getattr(owner, name)
    return owner, attribute


def _has(owner, attribute: str) -> bool:
    """Whether `mock.patch` would find `attribute` on `owner`, without building it.

    `trainmate.runtime` answers an unknown attribute through a module `__getattr__` that
    *constructs* the singleton — a Database against the athlete's own file, a live Google
    client off the credentials — and caches it for the rest of the process. So it is asked
    the question its own accessor asks, off the builder registry, rather than by reading
    the attribute (ARCHITECTURE §6).
    """
    from trainmate import runtime
    if owner is runtime:
        return attribute in vars(runtime) or attribute in runtime._BUILDERS
    return hasattr(owner, attribute)


class TestEveryPatchTargetStillResolves(unittest.TestCase):
    """A `patch("trainmate.a.b.c")` names a module and an attribute by string, so nothing
    checks it until the line runs. Move `c` out of `b` and every test that does not happen
    to execute that line keeps passing, while the ones that do fail somewhere unrelated.

    Resolving all of them in one place turns a move that orphans a seam into a single red
    test that names the target and the file it is written in.

    Only the string form needs this. `patch.object(module, "name")` and `patch.dict(obj)`
    are handed the object, so a name that has moved raises `AttributeError` at `start()` in
    whichever test uses it — loudly, and in the right place.
    """

    def test_every_patch_target_in_the_suite_names_something_that_exists(self):
        orphans = []
        for target, where in _patch_targets():
            try:
                owner, attribute = _walk_to_the_owner(target)
            except (ImportError, AttributeError) as failure:
                orphans.append(f"{target} ({where}): {failure}")
                continue
            if not _has(owner, attribute):
                orphans.append(f"{target} ({where}): {owner!r} has no {attribute!r}")
        self.assertEqual(
            orphans, [],
            "these patch targets no longer resolve, so they stub nothing — point each at "
            f"where the name lives now: {orphans}",
        )


if __name__ == "__main__":
    unittest.main()
