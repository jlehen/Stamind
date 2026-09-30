"""`data publish` and `data unpublish`: put the pages' files in the bucket, and take them out
again (DESIGN_miniapp_storage.md §9). The files themselves are `stamind/page_files/`.

Nothing printed here holds the page key or a file's name (§8): a failed request is named
by `bucket.describe`.
"""
import argparse
import os
import time

from stamind import runtime
from stamind.config import config
from stamind.output import notice
from stamind.page_files import bucket as _bucket
from stamind.page_files import sync
from stamind.text import cmd, green, red

# Google allows one write per second to one name, and check 3 writes its file twice (§15).
WRITE_GAP_SECONDS = 1.1

GUIDE = "of \"The pages' files in a bucket\" in the README"


class SetupError(Exception):
    """A check that failed, worded for the operator with the step to fix."""


def _passed(text: str) -> None:
    print(green(f"✓ {text}"))


def _target() -> sync.Target:
    """Check 1: a bucket, and the bot token."""
    if not config.storage_bucket:
        raise SetupError("No bucket is configured. Write its name in config.yaml as "
                         f"google.storage_bucket (step 5 {GUIDE}).")
    if not config.telegram_bot_token:
        raise SetupError("This terminal does not know the bot token. Give it the "
                         "TELEGRAM_BOT_TOKEN the bot runs with, or write the token in "
                         "config.yaml as telegram.bot_token.")
    where = sync.target()
    _passed(f"The config names the bucket {where.bucket}, and the bot token is known.")
    return where


def _sign_in(remote) -> None:
    """Check 2: Google accepts the service account's file."""
    try:
        remote.sign_in()
    except Exception as exc:
        raise SetupError(f"Google refused the service account's file "
                         f"{config.service_account_file} ({_bucket.describe(exc)}). It is "
                         "missing, or its key was revoked. See \"Google Calendar and the "
                         "service account\" in the README.")
    _passed("Google accepts the service account's file.")


def _guard(where: sync.Target, remote, force: bool) -> None:
    """Stops at a folder holding files this database never uploaded (§9.1)."""
    try:
        found = sync.strangers(runtime.db, where, remote)
    except Exception as exc:
        raise SetupError(f"The service account could not list the bucket "
                         f"({_bucket.describe(exc)}). Give it the role Storage Object User "
                         f"on this bucket (step 3 {GUIDE}).")
    if not found:
        return
    if force:
        print(f"--force: going on over {len(found)} files this database never uploaded.")
        return
    raise SetupError(f"This bot's folder in the bucket holds {len(found)} files this "
                     "database never uploaded, so another database published there. Nothing "
                     "was changed. If this database is the right one, for example one "
                     "restored from a backup, run the command again with --force.")


def _check_the_bucket(where: sync.Target, remote) -> None:
    """Checks 3 to 5: writing, reading as a page does, and no listing (§9.2)."""
    name = where.name(sync.CHECK)
    first, second = os.urandom(16).hex().encode(), os.urandom(16).hex().encode()
    try:
        remote.upload(name, first)
        time.sleep(WRITE_GAP_SECONDS)
        remote.upload(name, second)
    except Exception as exc:
        raise SetupError(f"The service account could not write a test file and write it "
                         f"again ({_bucket.describe(exc)}). Give it the role Storage Object "
                         f"User on this bucket (step 3 {GUIDE}).")
    _passed("The service account writes a file, and writes it again.")

    try:
        response = remote.download(name, sync.PAGES_ORIGIN)
    except Exception as exc:
        raise SetupError(f"The test file could not be downloaded ({_bucket.describe(exc)}).")
    if response.status_code != 200:
        raise SetupError(f"A download with no credential was refused (HTTP "
                         f"{response.status_code}). Give everyone (allUsers) the role Storage "
                         f"Legacy Object Reader on this bucket (step 4 {GUIDE}), and untick "
                         f"\"Enforce public access prevention\" (step 2).")
    if response.content != second:
        raise SetupError("A download with no credential returned the test file as it was "
                         "before it was written again: Google served an old copy.")
    if response.headers.get("Access-Control-Allow-Origin") not in ("*", sync.PAGES_ORIGIN):
        raise SetupError("Google did not send the header that lets a page from another "
                         "site read the file.")
    _passed("Anyone can download a file by its name, fresh, from the pages' site.")

    try:
        listed = remote.open_to_listing()
    except Exception as exc:
        raise SetupError(f"The listing test could not run ({_bucket.describe(exc)}).")
    if listed:
        raise SetupError("Anyone can list the bucket. Everyone (allUsers) holds a role that "
                         "lists, such as Storage Object Viewer: give them Storage Legacy "
                         f"Object Reader instead (step 4 {GUIDE}).")
    _passed("Nobody can list the bucket without a credential.")


def run_data_publish(args: argparse.Namespace) -> None:
    """Checks each step of the setup, then uploads every file again and deletes any other
    file in this bot's folder (§9.2)."""
    try:
        where = _target()
        remote = where.remote()
        _sign_in(remote)
        _guard(where, remote, args.force)
        _check_the_bucket(where, remote)
    except SetupError as problem:
        notice(f"✗ {problem}", red)
        return
    try:
        failed, deleted = sync.fill(runtime.db, where, remote)
    except Exception as exc:
        notice(f"✗ The upload stopped ({_bucket.describe(exc)}). Run "
               + cmd("sm data publish") + " again.", red)
        return
    if failed:
        notice(f"✗ {len(failed)} files were not uploaded, {', '.join(failed)}, so nothing "
               "was deleted. Run " + cmd("sm data publish") + " again.", red)
        return
    _passed(f"Every file is uploaded, and {deleted} other files are deleted.")
    print("The bot's next message carries the buttons that open them.")


def run_data_unpublish(args: argparse.Namespace) -> None:
    """Deletes this bot's files from the bucket and empties the record (§9.3)."""
    try:
        where = _target()
        remote = where.remote()
        _sign_in(remote)
        _guard(where, remote, args.force)
    except SetupError as problem:
        notice(f"✗ {problem}", red)
        return
    try:
        left = sync.remove(runtime.db, where, remote)
    except Exception as exc:
        notice(f"✗ The deletion stopped ({_bucket.describe(exc)}). Run "
               + cmd("sm data unpublish") + " again.", red)
        return
    if left:
        notice(f"✗ {left} files could not be deleted. Their record stays, so running "
               + cmd("sm data unpublish") + " again removes them.", red)
        return
    _passed("This bot's files are gone from the bucket, and the record is empty.")
    print("The bot's next message carries the buttons without them. To switch storage off "
          "for good, remove google.storage_bucket from config.yaml.")
