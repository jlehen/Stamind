# Renaming TrainMate to stamind

This document lists every place the name "TrainMate" lives, the decisions taken, and the
steps to rename it, in order. It is a one-off working document, like the `REORG_*.md` files
were. Delete it when the rename has landed.

A note on words. In this codebase a "plan" is the periodization. So this document says "the
rename" and "steps", never "the plan".

This file names the old strings on purpose. Keep it out of the substitution in step 1.

Survey date: 2026-09-21, at commit `2c2da87`.

## 1. State of the repo on the survey date

- All 22 local branches are merged into `main`. No branch holds unmerged commits.
- `main` is fully pushed. `origin` is `git@github.com:jlehen/TrainMate.git`.
- So no branch will conflict with a repo-wide substitution. This is a good moment.
- Two bots run from the main checkout: yours, and the companion one started by
  `piupiu-tm-bot.sh`. Both must be stopped before the database files are renamed.
- There are 11 worktrees under `.claude/worktrees/`. The `code-reorg` worktree has 6
  uncommitted files. The others are clean.
- No cron job, no systemd unit and no shell alias uses the name.
- `gh` is not installed. The GitHub rename goes through the web UI.
- Not checked: whether the name `jlehen/stamind` is free on GitHub.

## 2. Where the name lives

### 2.1 Tracked files

| Where | How much | Notes |
|---|---|---|
| Package directory `trainmate/` | 170 files | Every import, every `patch("trainmate....")` string in the tests, every `trainmate/x.py` path in the docs. |
| Root scripts | 3 files | `trainmate_cli.py`, `trainmate_web.py`, `trainmate_bot.py`. The wrappers `tm` and `tm-bot` exec them by path. |
| Lowercase `trainmate` | 2,538 lines | 1,287 in `tests/`, 975 in the package, 400 in `designs/`, 162 in `docs/`, 32 in `scripts/`. Mostly imports and file paths. |
| Display name `TrainMate` | 229 lines | CLI help, notices, README, the dashboard title in `static/index.html`, and five prompts that open with "You are TrainMate Coach". |
| Environment variables | 219 lines, 7 names | `TRAINMATE_RENDER`, `_FRONTEND`, `_WRAP_WIDTH`, `_CONFIG`, `_VERBOSE`, `_PARENT_RUN`, `_SOURCE`. |
| Short command `tm` | about 290 lines | The wrappers `tm` and `tm-bot`. `prog="tm"` in `trainmate_cli.py:82`. The variable `TM_BOT_SUPERVISED` in `tm-bot`. `journal.start_run(["tm-bot"])` in `trainmate/chat/app.py:167`. Every printed hint such as `tm workout adapt`: 131 lines in `designs/`, 44 in `docs/`, 35 in the package, 29 in `README.md`, 17 in `tests/`, 16 in `static/`. |
| Database file name | 1 default | `"trainmate.db"` in `trainmate/config.py:141`. Neither live config overrides it. `.gitignore` has 6 patterns for it. |
| OpenRouter app title | 1 line | `"X-Title": "TrainMate Coach"` in `trainmate/openrouter.py:351`. |

No file under `designs/` or `docs/` has the name in its file name.

### 2.2 Untracked local files

- `piupiu-tm.sh` and `piupiu-tm-bot.sh` set
  `TRAINMATE_CONFIG="//home/jlh/TrainMate/piupiu/config_piupiu.yaml"` and call `./tm` or
  `./tm-bot`. They hold the variable name, the directory path and the wrapper name.
- `piupiu/tm` and `piupiu/tm-bot`, the companion instance's own wrappers.
- `trainmate.db` and `piupiu/trainmate.db`, the two live databases.
- The hand-made snapshots: `trainmate.db.klausenpass`, `trainmate.db.pre-match-fix-...`,
  `trainmate.db.pre-revisions-...`, `trainmate.db.workoute_generate`, and
  `piupiu/trainmate.db.bak-ebike-match-...`.
- `TODO` and about 20 files under `design_audit/` mention the name in prose.
- `.claude/settings.local.json` may hold permission entries with the absolute path.

### 2.3 Identifiers stored outside the repo

These are the only two places where a plain substitution would break something.

**The workout event tag.** Every workout event the app writes to Google Calendar carries a
hidden property `source=TrainMate`. The constant is `WORKOUT_EVENT_TAG` in
`trainmate/gcal/event.py:24`. Normal calendar sync finds events by their stored event id.
`workout calendar sweep` is different: it looks for leftover events, and the tag is the only
way it can find them.

A real week. It is Wednesday. Thursday's ride is in the calendar, tagged `source=TrainMate`.
The constant is changed to `stamind`. Later the database row for that ride is deleted. The
sweep now asks Google for events tagged `source=stamind`. The Thursday event has the old tag,
so the sweep never sees it. It stays in the calendar until someone deletes it by hand.

**The context event tag.** Context events are tagged `source=trainmate-context`. That is the
default of `calendar_signal_tag` in `trainmate/config.py:459`. A comment there says an
external syncer writes the same string into the events it produces. Neither live config sets
the key, so both athletes use the default. If the default changes and the old events keep the
old tag, the app stops reading them.

### 2.4 What is safe to leave

- **Database contents.** A copy of the main database was scanned on the survey date. The name
  appears only inside old free text: one row of `plan_feedback.text`, one row of
  `macrocycles.strategy`, and four rows of `macrocycles.science_snapshot`. None is a key or
  is matched against. Leave them as history.
- **Journal logs.** They store the argv of past runs. They are a record of what ran. Leave
  them.
- **Old one-off scripts** in `scripts/migrate_*.py`. They have already run on both instances.
  Delete them rather than rename inside them.

## 3. Decisions taken

The author settled these four on 2026-09-21. The steps below follow them.

1. **Display spelling.** "Stamind" in prose, `stamind` for the package, and `STAMIND_*` for
   environment variables. All-lowercase reads oddly at the start of a sentence: "stamind
   needs at least one goal."
2. **Short command.** `sm` and `sm-bot` replace `tm` and `tm-bot`. It is the same length as
   `tm`, so no printed hint gets longer and nothing needs re-wrapping.
3. **Calendar tags.** A one-off script changes both tags on the events that already exist,
   run once per athlete. This follows the AGENTS.md rule: a one-off migration, no backward
   compatibility in the code.
4. **Designs.** The substitution runs inside `designs/` too. The designs cite module paths
   such as `trainmate/gcal/event.py`, and those would all go stale. The substitution is
   mechanical. It does not change what any design says.

The context tag has a second writer. `DESIGN_calendar_signal_ingest.md` §4 makes the string
`source=trainmate-context` a contract with an external syncer. That syncer is a separate
repo which reads a spreadsheet and drops one tagged event per day into the calendar. The
author changes it by hand to write `stamind-context`, on the same day as step 2. Otherwise
the events it writes after the rename carry the old tag, and the app ignores them.

## 4. The steps

### Step 0. Prepare

1. Stop both bots.
2. Snapshot `trainmate.db` and `piupiu/trainmate.db`.
3. Look at the 6 uncommitted files in the `code-reorg` worktree. Keep or discard them.
4. Remove all the worktrees except the one doing the rename. Every branch is merged. Their
   `config.yaml`, `venv` and `service_account.json` symlinks point at `/home/jlh/TrainMate`,
   which moves in step 5.

### Step 1. The code, in one worktree, as three commits

**Commit A: the package, the files and the display name.**

1. `git mv trainmate stamind`.
2. `git mv` the three root scripts to `stamind_cli.py`, `stamind_web.py`, `stamind_bot.py`.
3. Delete the old `scripts/migrate_*.py` files.
4. Substitute across all tracked text files, in this order: `TRAINMATE` to `STAMIND`, then
   `TrainMate` to `Stamind`, then `trainmate` to `stamind`.
5. Keep three things out of the substitution: this document, the value of
   `WORKOUT_EVENT_TAG`, and the default of `calendar_signal_tag`. Commit C changes the two
   tag values on purpose.
6. "stamind" is 2 characters shorter than "trainmate". So no line grows past 100 characters.
   Some wrapped paragraphs will look short. Leave them.

This commit must be atomic. The 132 `patch("trainmate.coach.engine.openrouter_client")` calls
and every import change together, or the tests cannot pass.

**Commit B: the short command.**

1. `git mv tm sm` and `git mv tm-bot sm-bot`.
2. Change `prog="tm"`, the variable `TM_BOT_SUPERVISED`, the `echo "tm-bot: ..."` lines in
   the wrapper, and the `journal.start_run(["tm-bot"], ...)` strings.
3. Change the printed hints with a word-boundary match on `tm`. About 290 lines.
4. Read this diff by hand. Two letters match things that are not the command, such as the
   temp-file prefix `tm-journal-test-` in `tests/test_journal.py`. Those are harmless, but
   each hit should be looked at once.
5. AGENTS.md names `tm-bot` and `trainmate_bot.py` in its file-size rule. Update that
   sentence.

**Commit C: the stored identifiers.**

1. Change the default database name in `config.py` to `stamind.db`. Change the 6 `.gitignore`
   patterns and the `#database:` line in `config_template_full.yaml`.
2. Change `WORKOUT_EVENT_TAG` to `"stamind"` and the `calendar_signal_tag` default to
   `"stamind-context"`. Update the comment above the default, which explains why the old
   string was kept.
3. Add `scripts/migrate_rename_to_stamind.py`. For the instance named by `STAMIND_CONFIG`, it
   does two things:
   - It renames `trainmate.db` to `stamind.db` in that instance's data directory. It refuses
     to run if a `-wal` or `-shm` file is present, because that means a process still has the
     database open.
   - It lists every calendar event tagged `source=TrainMate` or `source=trainmate-context`,
     past and future, and patches the tag to the new value. It prints how many it changed.

Across the three commits, update `docs/ARCHITECTURE.md` and the vocabulary section of
AGENTS.md.

Then run the full suite under the memory cap. It must show the 4 known failures and no fifth.
A fresh worktree needs `config.yaml` and `venv` symlinked in first.

### Step 2. Migrate the data

1. Land the branch on `main`: rebase, then fast-forward.
2. Run the script once with your config, and once with
   `STAMIND_CONFIG=piupiu/config_piupiu.yaml`.
3. Run `sm workout calendar sweep` for each athlete. It lists events by the new tag. If it
   still sees the app's events, the re-tag worked.
4. The author changes the external syncer, in its own repo, to write `stamind-context`. Do
   this before the syncer's next run, so that no new event gets the old tag.

### Step 3. Fix the local untracked files

1. `piupiu-tm.sh` and `piupiu-tm-bot.sh`: the new variable name, the new path, the new
   wrapper name. Rename the two files to match.
2. `piupiu/tm` and `piupiu/tm-bot`: the same.
3. The old `trainmate.db.*` snapshots show up as untracked once `.gitignore` changes. Rename
   them to `stamind.db.*`, or move them into a backup folder outside the repo.
4. `TODO` and `design_audit/` are untracked prose. Run the same substitution over them, or
   leave them. Nothing reads them.

### Step 4. GitHub

1. Push `main`. This needs an explicit go-ahead, per the git policy.
2. In the web UI: Settings, General, Repository name. Enter `stamind`.
3. `git remote set-url origin git@github.com:jlehen/stamind.git`.
4. GitHub redirects the old URL, for the web and for git, until a new repo takes the old
   name. So nothing breaks between sub-steps 2 and 3.
5. The repository description is a separate field on the same page.
6. Optional: six stale `worktree-*` branches sit on the remote and can be deleted.

### Step 5. The directory, last

1. `mv ~/TrainMate ~/stamind`.
2. Recreate `venv`. Its scripts start with `#!/home/jlh/TrainMate/venv/bin/python3`, so
   `venv/bin/pip` breaks after the move. `venv/bin/python` itself keeps working.
3. Move `~/.claude/projects/-home-jlh-TrainMate` to `~/.claude/projects/-home-jlh-stamind`.
   Claude Code keys its project memory on the directory path. Without this move the memory
   starts empty. About 30 old per-worktree project directories sit beside it and can be
   deleted.
4. Update the memory files that say "TrainMate", mainly `project-trainmate-vocabulary.md`.
5. Fix any absolute path in `.claude/settings.local.json`.
6. Restart both bots.

### Step 6. Outside the repo, optional

- The Telegram bot's display name, through BotFather `/setname`. The token does not change.
- The Google Calendar display names.
- OpenRouter: the app title changes with commit A. Usage statistics there will split into
  an old app and a new one.

## 5. Done when

- `git grep -i trainmate` returns only `scripts/migrate_rename_to_stamind.py`, which names
  the old strings on purpose.
- The full suite shows its 4 baseline failures and nothing else.
- `./sm status` works for both athletes.
- Both bots answer on Telegram.
- `sm workout calendar sweep` finds the app's events under the new tag.
- This document is deleted.
