"""The step after every command (DESIGN_miniapp_storage.md §6), and the guard, the fill and
the removal that `sm data publish` and `sm data unpublish` run (§9).
"""
import hashlib
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from stamind import calendar_days, clock, journal, runtime
from stamind.clock import month_end, month_start
from stamind.config import config
from stamind.cli.render import calendar_page, plan_page
from stamind.output import aside
from stamind.page_files import bucket as _bucket
from stamind.page_files import recipe
from stamind.text import green

# The labels of the two files that belong to no month (§4).
INDEX = "calendar/index"
PLAN = "plan"
# The label of the test file `sm data publish` writes. It is never a page's (§9.2).
CHECK = "check"

# What all the uploads of one command share. A first guess, to be measured (§6, §15).
UPLOAD_SECONDS = 3.0

# The site that serves the pages, which `sm data publish` downloads as (§9.2, check 4).
PAGES_ORIGIN = "{0.scheme}://{0.netloc}".format(urlsplit(calendar_page.PAGE_URL))


class Target(NamedTuple):
    """This bot's folder in the operator's bucket, and the page key that opens its files."""
    bucket: str
    folder: str
    key: bytes

    def name(self, label: str) -> str:
        return recipe.file_name(self.key, label)

    def address(self, name: str) -> str:
        """A file's full address, the record's key (§6)."""
        return f"{self.bucket}/{self.folder}/{name}"

    def remote(self) -> "_bucket.Bucket":
        return _bucket.Bucket(self.bucket, self.folder)


def target() -> Optional[Target]:
    """None when the config names no bucket, or when this process knows no bot token."""
    bucket, token = config.storage_bucket, config.telegram_bot_token
    if not bucket or not token:
        return None
    return Target(bucket, recipe.folder(token), recipe.page_key(token))


def published(dbh, where: Target) -> bool:
    """Whether `sm data publish` published this database here: the index file went up once
    (§6, step 1). A failed first try leaves a row with no fingerprint."""
    row = dbh.get_page_file(where.address(where.name(INDEX)))
    return row is not None and row["fingerprint"] is not None


def button_params(dbh) -> str:
    """What storage adds to each page's address, or "" when this database was never
    published here (§8)."""
    where = target()
    if where is None or not published(dbh, where):
        return ""
    return f"&k={recipe.key_param(where.key)}&b={where.bucket}&f={where.folder}"


def build(dbh, today: str, every_month: bool = False) -> Dict[str, Dict[str, Any]]:
    """Each file's content by label: the months the window touches, or every month from the
    first when `every_month`, then the index file and the plan file (§4, §6 step 2)."""
    window = calendar_page.window(today)
    cal = calendar_days.gather(dbh, month_start(window[0]), month_end(window[1]), today)
    first = min(dbh.first_training_day() or window[0], window[0])[:7]
    months_cal = cal
    if every_month:
        # One pass over the whole history (§9.2).
        months_cal = calendar_days.gather(dbh, first + "-01", month_end(window[1]), today)
    files = calendar_page.month_files(months_cal)
    at = clock.now()
    files[INDEX] = calendar_page.index_file(cal, at, window, first, window[1][:7])
    files[PLAN] = plan_page.plan_file(cal, at)
    return files


def rebuilt(label: str, today: str) -> bool:
    """Whether the step after a command builds this file: the index file, the plan file, or
    a month the window touches (§6 step 2)."""
    if label in (INDEX, PLAN):
        return True
    start, end = calendar_page.window(today)
    return calendar_page.month_label(start[:7]) <= label <= calendar_page.month_label(end[:7])


def fingerprint(content: Dict[str, Any]) -> str:
    """What the record compares: the content before encryption, without the stamp (§6)."""
    unstamped = {key: value for key, value in content.items() if key != "at"}
    return hashlib.sha256(recipe.dumps(unstamped)).hexdigest()


def _upload(dbh, where: Target, remote, label: str, content: Dict[str, Any],
            seconds: float) -> bool:
    """Uploads one file and writes its record. A failure goes to the journal and the
    record, never to the screen (§6 step 5, §10)."""
    name = where.name(label)
    try:
        remote.upload(name, recipe.seal(where.key, content), seconds)
    except Exception as exc:
        error = _bucket.describe(exc)
        journal.note(f"{label} was not uploaded: {error}", lvl="warn", label=label,
                     error=error)
        dbh.record_page_error(where.address(name), label, error)
        return False
    dbh.record_page_upload(where.address(name), label, fingerprint(content))
    return True


def _in_upload_order(labels, this_month: str) -> List[str]:
    """The month holding today first, then the other months, the index file, the plan."""
    def rank(label: str) -> Tuple[int, str]:
        if label == this_month:
            return 0, label
        if label == INDEX:
            return 2, label
        if label == PLAN:
            return 3, label
        return 1, label
    return sorted(labels, key=rank)


def after_command() -> None:
    """The step after every command, whatever its outcome (§6). Never raises: a command
    never fails because of an upload. A terminal reads one line when files went up."""
    try:
        where = target()
        if where is None or not published(runtime.db, where):
            return
        uploaded = _upload_changes(runtime.db, where)
        if uploaded:
            aside(f"Pages' files updated: {uploaded} file(s) uploaded to the bucket.", green)
    except Exception as exc:
        journal.note("the pages' files were not refreshed", lvl="warn",
                     error=_bucket.describe(exc))


def _upload_changes(dbh, where: Target) -> int:
    """Steps 2 to 5 of §6, within `UPLOAD_SECONDS`. Returns how many files went up."""
    today = clock.today_str()
    files = build(dbh, today)
    record = dbh.get_page_files()
    deadline = time.monotonic() + UPLOAD_SECONDS
    remote = where.remote()
    count = 0
    calendar_uploaded = False
    for label in _in_upload_order(files, calendar_page.month_label(today[:7])):
        stored = record.get(where.address(where.name(label))) or {}
        # A file whose last upload failed goes again, even with the same content (§6 step 3).
        due = stored.get("error") or stored.get("fingerprint") != fingerprint(files[label])
        if label == INDEX and calendar_uploaded:
            due = True
        if not due:
            continue
        left = deadline - time.monotonic()
        if left <= 0:
            break
        if not _upload(dbh, where, remote, label, files[label], left):
            continue
        count += 1
        if label not in (INDEX, PLAN):
            calendar_uploaded = True
    return count


def strangers(dbh, where: Target, remote) -> List[str]:
    """The files in this bot's folder that the record does not know, the test file of
    `sm data publish` aside (§9.1)."""
    known = dbh.get_page_files()
    check = where.name(CHECK)
    return [name for name in remote.names()
            if name != check and where.address(name) not in known]


def fill(dbh, where: Target, remote) -> Tuple[List[str], int]:
    """Uploads every file with no time limit, then deletes every other file in the folder
    and forgets its row (§9.2). Returns the labels that failed, and how many files were
    deleted; nothing is deleted when an upload failed."""
    files = build(dbh, clock.today_str(), every_month=True)
    written, failed = set(), []
    # The index file goes last: commands upload once its row exists (§6, step 1).
    for label in sorted(files, key=lambda label: label == INDEX):
        if not _upload(dbh, where, remote, label, files[label], _bucket.SECONDS):
            failed.append(label)
            continue
        written.add(where.name(label))
    if failed:
        return failed, 0
    deleted = 0
    for name in remote.names():
        if name in written:
            continue
        remote.delete(name)
        dbh.forget_page_file(where.address(name))
        deleted += 1
    return [], deleted


def remove(dbh, where: Target, remote) -> int:
    """The three steps of §9.3: the index file, every other file in the folder, then the
    rows left. Returns how many files are left; their rows stay, so running it again
    removes them."""
    index = where.name(INDEX)
    remote.delete(index)
    dbh.forget_page_file(where.address(index))
    left = 0
    for name in remote.names():
        try:
            remote.delete(name)
        except Exception:
            left += 1
            continue
        dbh.forget_page_file(where.address(name))
    if not left:
        dbh.forget_page_files()
    return left


def failures(dbh, where: Target) -> List[Dict[str, Any]]:
    """The rows of this folder whose last upload failed (§10)."""
    prefix = where.address("")
    return [row for address, row in dbh.get_page_files().items()
            if address.startswith(prefix) and row["error"]]
