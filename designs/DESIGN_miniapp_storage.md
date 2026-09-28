# Mini app storage: the pages read their data from encrypted files

**Status:** Designed, not implemented · **Date:** 2026-09-28 ·
**Branch:** `worktree-miniapp-storage`

This design comes out of an interview with the author (twelve decisions, §14), then a
red-team pass by three reviewers, then a pass that weighed each finding against what it
costs to maintain. What was decided is written here as the contract. What was left out is
in §16.

The words this document uses:

- **A page** is a mini app: a web page opened inside Telegram from a button of the bot's
  keyboard. This design covers two, the calendar and "Goals & plan". The gym logger is
  untouched.
- **The button's data** is what a page gets today, in the web address of its button.
- **The window** is the ten weeks the calendar button carries: 28 days back and 42 days
  ahead of today.
- **The bucket** is a folder of files at Google Cloud Storage, which the operator creates.
- **A month file** holds one calendar month of the calendar. **The index file** holds what
  belongs to no month. **The plan file** holds the "Goals & plan" page.
- **The page key** is the secret that opens the files. The button's address carries it.
- **The stamp** is the "as of Wed 07:02" a page prints.
- **The record** is what Stamind remembers of each file it uploaded.
- **The operator** is whoever installed Stamind and runs its commands in a terminal.

## 1. The problem

A page gets its data in the address of its button, after the `#`. Telegram refuses a
keyboard above about 9.9 KB, all buttons together. So the calendar has 5 KB and "Goals &
plan" 2 KB. The workout texts do not fit: with them, the calendar's ten weeks need about
47 KB (DESIGN_calendar_miniapp.md §5, §8). A mesocycle's long text runs to 3 or 4 KB, so it
does not fit either.

The need is to get more data into the pages. Sending more than 4,096 bytes back from a
page is not needed today (§16).

## 2. What it does

It is Wednesday 30 September. The morning message went out at 07:02. The athlete opens the
calendar at 07:10. The page draws at once from the button's data, as it does today. A
moment later the files arrive and the page draws again. Nothing moves on the grid, because
the data is the same. She taps Thursday. Under "Planned" the sheet now holds the whole
workout text. The "💬 Full day in chat" button is gone, because the sheet already says
everything the chat would.

At 12:30 she runs. At 14:05 the operator runs `sm workout list` in a terminal. The command
pulls the run from Garmin. September's data changed, so Stamind uploads September's file.

At 18:00 she opens the calendar. Her phone still holds the keyboard of 07:02. The page first
draws the morning's state, with the run not done. Then the files arrive. Wednesday's cell
turns green, and the stamp says "as of Wed 14:05".

She taps the left arrow four times and reaches May. The page downloads May's file and
draws it. Today the arrow stops at September.

She opens "🎯 Goals & plan" and taps the October mesocycle. The sheet shows its dates, its
one-line summary, and its whole long text. The "💬 Why, in chat" button is gone.

**When something fails.** The train enters a tunnel and nothing downloads. Both pages then
behave exactly as they do today: the button's data, ten weeks, no long text, and the two
chat buttons. The same holds for an operator who never configured a bucket.

## 3. Why files in a bucket

The criteria were ease of setup for whoever installs Stamind, little maintenance, decent
latency, and room for later features. Ease of setup weighed most.

One rule decides what is possible. A page is loaded over HTTPS, so it can only call HTTPS
on a named host that holds a valid certificate. It cannot open a TCP connection, and the
browser blocks a call to plain HTTP whatever the payload. So somebody must hold a
certificate, and the options differ by who.

| Option | Why it was not chosen |
|---|---|
| Stay inside Telegram | The limit stays. Telegram's storage for pages is written by the page only, never by the bot. |
| Own domain and web server | Too much setup for an operator, and it does not work behind a home router. |
| A tunnel (Tailscale Funnel) | Works, and stays the answer the day a page must write more than 4 KB. Not needed for reading. |
| A message service (pub/sub) | Carries messages, not questions and answers. Google's own is meant for servers, not pages. |
| A rented function as middleman | A second program at a provider, and the data in two places. |
| Plain HTTP or TCP with own encryption | Blocked by the browser. The encryption idea was kept, the transport was not. |
| **Encrypted files in a bucket** | **Chosen.** Nothing runs on the operator's machine, and no door opens onto the database. |

Google Cloud Storage was chosen because the operator already has a Google project and a
service account, made for Google Calendar (D1).

**Storage is optional (D3).** With no bucket in the config, nothing is built, nothing is
uploaded, and the buttons' addresses are the ones of today.

## 4. The files

| File | Label | What it holds | Built |
|---|---|---|---|
| A month file | `calendar/2026-09` | The days of that month: each day's cell and its sheet, workout text included. Nothing else. | After every command, for the months the window touches. Older months by `sm data publish` only (§9). |
| The index file | `calendar/index` | Today's date, the stamp, the goals, the mesocycles, the last day of the schedule, and the first and last month that have a file. | After every command. |
| The plan file | `plan` | What the "Goals & plan" button carries, plus each mesocycle's whole long text. | After every command. |

A file's name in the bucket never changes (D9). Writing a file again replaces its content
under the same name, so a page always finds the newest content under the name it computes.

**The shape.** A month file is `{"v": 1, "days": {…}}`, with each day exactly as the
button's data writes it (DESIGN_calendar_miniapp.md §5), and every day's sheet present. The
index file is the button's data without `days` and without `fit`, plus `first` and `last`,
two months written as `"2025-03"`. The plan file is the plan button's data, where each
mesocycle also carries its long text.

**Which months have a file.** Every month from the first to the last, even a month with
nothing in it. The first is the month of the earliest day on which the database holds a
session or an activity. The last is the month that holds the window's last day. The athlete
took March and April off: both months have a file with no day in it, so the page can tell
an empty month from the end of the history.

**No text in a file is wrapped.** The workout text and the mesocycle's long text go in as
stored, without `wrap_text`. The browser wraps them. This is not a matter of looks. The
bot runs its commands with a width of 900, and its scheduler with the default of 80. If a
file's content depended on who built it, every file would be uploaded again at each change
of hands, and the text would break in the middle of sentences.

**The mesocycles stay one list**, in the index file and in the button. Both build it from
the first day of the month that holds the window's first day, to the last goal. It is Sunday
27 September. The window starts on 30 August, so the list starts on 1 August, and a
mesocycle that ended on 20 August is in it. Both lists start on the same day, so no colour
shifts between the first draw and the second. The legend lists the mesocycles that touch the
month shown. A month before that list has grey strips and an empty legend (§16).

## 5. The key, the names and the encryption

The programmer must follow this recipe word for word, in Python and in the page. Both use
functions their platform already has: the `cryptography` package, and the browser's
`crypto.subtle`.

- **The page key** is 32 bytes, computed from the bot token (D6) with HKDF, a standard
  one-way function, using SHA-256 and the label `stamind-miniapp-v1`. Nobody can compute
  the token back from it. It is never computed the way Telegram computes its own secrets
  from the token (HMAC with the word `WebAppData`, or plain SHA-256), because the page key
  travels in an address and those secrets must not.
- **The key that encrypts** is HKDF of the page key with the label `file-key`.
- **A file's name** is HKDF of the page key with the label `name:` followed by the file's
  label, 16 bytes, written in hexadecimal. `name:calendar/2026-09` gives September's name.
  Nobody can guess a name, or compute the page key from one.
- **The folder** is the bot's public number, the part of the token before the colon. It
  stays the same when the token is revoked. Each bot has its own.
- **A file's content** is the JSON, compressed with zlib as the button's data is, then
  encrypted with AES-GCM. AES-GCM needs 12 bytes that are never used twice with one key.
  Every upload draws them with `os.urandom(12)` and writes them at the head of the file.
  They are never computed from the file's name or from a counter.
- **The address the page downloads** is
  `https://storage.googleapis.com/storage/v1/b/BUCKET/o/FOLDER%2FNAME?alt=media`. Google
  answers a page from another site on this address without any rule set on the bucket. The
  plain address does not.

The page keeps the page key and the decrypted data in memory only. It writes neither to
the browser's storage.

**Who can read what.** Anyone who holds a file's name can download the file, and see its
size and the time it was last written. Only the page key opens it. Anyone who holds a
button's address holds the page key (§16).

## 6. After every command

Every command runs through `run_once` in `stamind_cli.py`: one typed in a terminal, one
the bot starts, one the scheduler starts. When a command has run, whatever its outcome,
Stamind takes five steps.

1. **It checks that this database was published.** It looks in the record for the index
   file's address. If the record has none, Stamind stops here, silently. Only `sm data
   publish` starts the uploads (§9).
2. **It builds** the months the window touches, as whole months, then the index file and
   the plan file. It is Sunday 27 September: the window runs from 30 August to 8 November,
   so Stamind builds August, September, October and November.
3. **It compares** each file with the record. What is compared is the content before
   encryption, without the stamp.
4. **It uploads** the files that differ, the month that holds today first. When any file
   of the calendar was uploaded, the index file is uploaded too, with the time of this
   command as its stamp. Each upload is one request, which carries the instruction "do not
   cache". Without it, Google would serve the old content for up to an hour.
5. **It writes the record** of each file, once that file's upload succeeded.

It never deletes a file. Only the two commands of §9 delete.

**Why build after every command, and not after a write.** A command that only reads can
still change the data, because it pulls from Garmin and from Google Calendar first.

**Why step 1.** It is Wednesday. Someone works in a git worktree and runs
`./sm workout list` there to look at a change. The worktree's `config.yaml` is a link to
the live one, so the command has the live bot token and the live bucket's name. It computes
the same names as the live bot. But its database is its own, and it is empty. Without
step 1 it would upload empty months over the athlete's files. With step 1 its record is
empty, so it uploads nothing. The same rule keeps the test suite from uploading.

**The record** is a table, `page_files`, with one row per file: the file's full address
(bucket, folder and name) as the key, its label, the fingerprint of the content last
uploaded, the time of that upload, and the error of the last attempt when it failed. The
key is the full address, which is computed from the bot token. So a copy of the live
database, run by the test bot with its own token, finds no row of its own and uploads
nothing until `sm data publish` is run for it. A bucket renamed in the config does the same.

**The reply waits for the upload.** The bot sends a command's last text when the process
ends. So the athlete waits for the upload, and the file is there when she opens the page.
The other order would let her open the calendar before the file arrives, and see her run
drawn as done, then as not done.

**Time.** All the uploads of one command share 3 seconds. Past them Stamind gives up, and
the next command uploads what is left. A command never fails because of an upload. The
Google libraries are imported only when there is something to upload, because importing
them takes about 0.3 seconds. The 3 seconds are a first guess: upload times were never
measured, so they are measured on the real bucket before the limit is fixed.

**What it costs a command that uploads nothing.** Reading the four months from the
database takes about 52 ms, against 43 ms for the ten weeks, on the test copy of the
author's database. Wording the ten weeks takes about 31 ms. Wording four whole months
with their workout texts was not timed.

## 7. The pages

Both pages draw every text from a file as plain text, never as HTML, as they do today with
the button's data. A workout text is written by a model and a goal's description by the
athlete, so neither may run as code in the page.

### 7.1 The calendar

1. **The page draws at once** from the button's data, as today.
2. **It downloads** the index file and the file of the month shown, both at once, when the
   button's address carries a page key.
3. **When the index file arrives**, its fields replace the button's: today's date, the
   goals, the mesocycles, the last day of the schedule. The months the arrows reach now run
   from `first` to `last`.
4. **When a month file arrives**, its days replace that month's days. The page then draws
   the month shown again. A file that arrives for a month she has left changes nothing on
   screen.
5. **When she turns to a month**, the page downloads its file, unless it already has it.

The page keeps one set of data, which starts as the button's data. The drawing code reads
that one set and does not know where a day came from.

**A month is in one of three states.** Its file arrived: the month is drawn from it, and
every day has its sheet. Its file is on its way: the month is drawn from what the page
already has, with "Loading…" under the grid. Its file could not be had: the month is drawn
the same way, with "This month could not be loaded." under the grid. Turning away and back
tries again.

**A file that cannot be used counts as missing.** That covers a file that cannot be
downloaded, one that cannot be decrypted, and one that says another version than the page
reads. The page never shows an error in place of the calendar because of a file.

**The chat button (D4).** "💬 Full day in chat" sits under a day with a session for as long
as that month's file has not arrived. The message "This day's details did not fit" is for
those days too, as today.

**The stamp** shows the later of two times: the button's and the index file's. It is
Wednesday 18:00. Nothing changed since 07:02, so nothing was uploaded. She sends "Today" to
the bot and opens the calendar. The button says 18:00 and the index file says 07:02. The
page says "as of Wed 18:00". If the page showed the file's time alone, she would read
07:02, think the calendar old, send another message, and still read 07:02.

### 7.2 Goals & plan

The page draws at once from the button's data, downloads the plan file, and draws again
from it. A tapped mesocycle shows its dates, its summary and its whole long text.

"💬 Why, in chat" is shown only when the plan file did not arrive. The long text in the
file is the one `bot mesocycle` prints, the text behind the chat's "Tell me more". It is
not what `plan show` prints, which is the list of mesocycles the page already draws.

The stamp follows the calendar's rule.

## 8. The button's address

Storage adds three things to each page's address: the page key as `k=`, the bucket's name
as `b=`, and the folder as `f=`. That is about 120 characters per page, so 240 for the
keyboard. Each page's budget shrinks by what storage adds to its own address. The
keyboard's worst case was 9,579 bytes, and Telegram accepted 9,921.

The bot adds them only when the config names a bucket and the record says this database
was published (§6, step 1). Otherwise the addresses are the ones of today.

No journal line, no error message and no output of the commands of §9 holds the page key or
a button's address. The bot already writes to the journal the text of an error raised
while it builds the keyboard, so that code names what failed and never quotes the address.

## 9. The two commands

### 9.1 The guard both commands start with

Both commands change the athlete's files on purpose, so step 1 of §6 cannot protect them.
They start with a guard of their own.

The command lists its folder in the bucket. If the folder holds a file that the record does
not know, the command changes nothing, and says that another database published here.
`--force` makes it go on.

It is Wednesday. Someone works in a git worktree whose `config.yaml` is a link to the live
one, and types `./sm data publish` there to try it. The command has the live bot token and
the live bucket, so its folder is the athlete's. The worktree's database is its own, and
its record is empty. The folder holds 30 files that the record does not know, so the
command stops. Without the guard it would upload the worktree's database over her files.
`./sm data unpublish` typed there would delete them.

**What passes by itself.** A first `sm data publish`, because the folder is empty. One
after a new bot token, because this database uploaded the files under the old names, so
the record knows them. The test file of check 3 never counts, so a run that was
interrupted does not block the next one.

**When `--force` is right.** The guard also stops one honest case: a database restored
from a backup. The backup's record does not know the files that were uploaded after it was
taken. The operator then runs `sm data publish --force`.

### 9.2 `sm data publish`

It checks each step of the setup and, when all pass, uploads every file again and deletes
any other file in its folder. The guard runs after check 2, which it needs in order to
list the folder.

**The checks.** Each failed check names the step of the README's guide that is wrong.

| # | Check | What a failure means |
|---|---|---|
| 1 | The config names a bucket, and this terminal knows the bot token. | No bucket configured. Or the token is given to the bot through the variable `TELEGRAM_BOT_TOKEN`, and the terminal does not have it. |
| 2 | Google accepts the service account's file. | The file is missing, or its key was revoked. |
| 3 | The service account uploads a test file, then writes it again. | It lacks the role `Storage Object User` on this bucket. |
| 4 | The test file is downloaded with no credential, the way the page does it. The answer must carry the content written a moment before, and the header that lets a page from another site read it. | Reading is not open to everyone, or "Enforce public access prevention" is still ticked, or Google served an old copy. |
| 5 | A listing with no credential is refused. | Everyone was given `Storage Object Viewer`, the role Google's own guide names first. It lets anyone list the bucket. |

**Then the fill.** It builds every month from the first to the last, in one pass over the
database, and uploads every file with no time limit. Then it lists its folder, deletes
every file it did not just write, and removes those files' rows from the record. The
listing asks for the folder's name followed by a slash, so a bot numbered `123456789` never
touches the folder of `1234567890`.

**When to run it.** After the setup. After a new bot token. And whenever older months are
missing or look wrong.

**What a new bot token does.** The names are computed from the token, so they all change.
The record holds no row under the new names, so commands upload nothing. The bot's
keyboard carries no page key, so the pages behave as today. The operator runs
`sm data publish`: every file is uploaded under its new name, and the files under the old
names are deleted. Until he runs it, the old files stay in the bucket, readable with the
old key.

### 9.3 `sm data unpublish`

It undoes `sm data publish`: it removes this bot's files from the bucket, and leaves the
database as it was before `sm data publish` was ever run. After the guard it takes three
steps, in this order.

1. **It deletes the index file, and removes its row from the record.** From then on no
   command uploads (§6, step 1), and the bot's next message carries the buttons of today,
   with no page key (§8).
2. **It deletes every other file in its folder**, and removes each file's row as the file
   goes. Files left under the names of an older bot token go too.
3. **It removes the rows left in the record**, such as those of a bucket the config named
   before. The record is then empty.

The index file goes first, so that a command running at the same moment stops uploading
behind the deletion. When a deletion fails, the command says how many files are left. Their
rows are still in the record, so running it again passes the guard and removes them.

It needs what checks 1 and 2 of `sm data publish` look at: the bucket's name in the config,
the bot token, and the service account's file.

**Nothing is lost.** Every file is built from the database, so `sm data publish` brings
them all back. This is why the command asks for no confirmation.

**A deleted file cannot be downloaded any more**, even while Google keeps it for seven days
(§11, step 1). So the command is also the fastest way to take the files away when a
button's address has leaked.

**What the athlete sees.** It is Friday. The operator runs `sm data unpublish` at 10:00.
Her phone still holds the keyboard of 07:02, whose buttons carry the page key. She opens
the calendar at 10:30. The page draws from the button's data, asks for the files, and finds
none. It shows the ten weeks, as it did before storage, with "This month could not be
loaded." under the grid. The bot's next message brings the buttons without a page key, and
the note is gone.

**To switch storage off for good**, run `sm data unpublish`, then remove the bucket's name
from `config.yaml`. With the name still there, `sm status` keeps saying that this database
was never published (§10).

## 10. When an upload fails

Each failed upload goes to the journal, with the file's label, such as `calendar/2026-09`,
and the type of the error. The error's own text is left out, because it holds the file's
address. Nothing is sent to anyone (D8): the athlete is not blocked, so nobody needs to be
woken.

`sm status` shows one line in two cases, both only when the config names a bucket:

- the last upload failed;
- this database was never published under this bot token, and `sm data publish` has to be
  run.

## 11. The operator's setup

The README gets a guide with these steps. Step 3 must be tried on a real bucket before the
guide is written (§15).

0. Check that billing is enabled on the Google project. Google asks for a payment method
   even when nothing is charged.
1. Create a bucket for Stamind alone. Its name is public, so nothing personal goes in it.
   Pick any region. Untick "Enforce public access prevention on this bucket". Unticking
   "Soft delete policy" is optional: with it on, Google keeps each replaced file for seven
   days, which costs under a cent a month.
2. Give the service account the role `Storage Object User` on this bucket, and no role on
   the project.
3. Give everyone (`allUsers`) the role `Storage Legacy Object Reader` on this bucket. This
   role lets anyone download a file by its name, and nobody list the bucket.
4. Write the bucket's name in `config.yaml`, as `google.storage_bucket` (D10).
5. Restart the bot. It reads `config.yaml` once, when it starts.
6. Run `sm data publish`. The bot's next message carries the new buttons.

To switch storage off again, see §9.3.

**Two instances.** An operator who runs two instances does steps 4 to 6 once per
instance, each with its own config. Both can share one bucket, because each bot has its
own folder in it. When the two use two service accounts, each account gets the role of
step 2.

**The price.** Google's free allowance covers three regions in the United States only. In
Frankfurt, 30,000 uploads a month cost $0.15, and Stamind makes a few hundred.

**Two more lines in the README.** `config.yaml` and the service account's file should be
readable by their owner only (`chmod 600`), because the bot token now also opens the
athlete's files. And when a phone is lost or a button's address has leaked: revoke the
token with BotFather, write the new one in the config, restart the bot, run
`sm data publish`.

## 12. Where things live

- A new package under `stamind/` holds three jobs: the key, the names and the encryption
  (§5); the four requests to Google, which are upload, download, list and delete; and the
  step after a command (§6) together with the fill (§9).
- `stamind/cli/render/calendar_page.py` and `plan_page.py` build the files' content from
  the list of days, beside the buttons' data.
- `stamind_cli.py`: `run_once` calls the step after a command.
- `stamind/cli/data/`: `sm data publish` and `sm data unpublish`. `stamind/cli/status.py`:
  the line of §10.
- `stamind/chat/app.py`: `_page_buttons` adds the three parts to each address (§8).
- `stamind/config.py` and `config_template.yaml`: `google.storage_bucket`.
- `stamind/db/schema.py`: the `page_files` table, with `SCHEMA_VERSION` 23. A one-off
  script under `scripts/` creates the table in both live databases.
- `miniapp/`: one new file for the key, the names, the download and the decryption, shared
  by both pages. `calendar_logic.js`, `calendar.js` and `plan.js` get the rules of §7.
- `requirements.txt` lists `cryptography`, which is installed and not listed. No new
  package is needed.
- `README.md` gets the guide of §11. `docs/ARCHITECTURE.md` gets the package, the command,
  the table and the config key.

## 13. Tests

The test suite refuses any network connection, so nothing in it reaches Google. The real
bucket is tested by `sm data publish`, by hand.

- The split into months, the names, the comparison with the record and the list of files
  to delete are plain functions, tested on plain data.
- The four requests go through one place that the tests replace.
- **The key, the names and the encryption** get one fixed example that both languages
  hold: a Python test produces it and a node test opens it. `miniapp/tests/calendar.test.mjs`
  already holds such a constant for the button's data.
- **A database that was never published uploads nothing.** This is the rule that protects
  the worktrees and the suite itself.
- A file's content is the same whatever width the process wraps at.
- `sm data unpublish` leaves an empty record, and deletes the files of its own folder only.
- Both commands stop at a folder that holds a file the record does not know, and go on
  with `--force`. After a new bot token, `sm data publish` goes on without it.
- On the page: a month file replacing the button's days, the three states, a file of
  another version counting as missing, the chat button following the month's file, the
  stamp taking the later time, and the legend listing the month's mesocycles.

## 14. What was decided

The author answered each of these in the interview.

| ID | Topic | Decision |
|---|---|---|
| D1 | Provider and cost | Google Cloud Storage. A payment method is acceptable. The operator picks the region. |
| D2 | What the file holds | Each page's whole data, long texts included. The buttons stay as today and are the fallback. The gym logger is untouched. |
| D3 | Storage is optional | With no bucket configured, the pages behave as today. |
| D4 | Chat buttons | "💬 Full day in chat" and "💬 Why, in chat" are shown only when the full text could not be downloaded. |
| D5 | Freshness | The files are uploaded after every command, also one run in the terminal. When the download worked, the page draws from the file. |
| D6 | Key | Computed from the bot token, so nothing new is stored and a test bot has its own key. |
| D7 | Setup | By hand, from a guide in the README, plus a command that tests the setup and names the step that is wrong. |
| D8 | Failures | Each failed upload goes to the journal, and `sm status` shows one line. Nothing is sent to anyone. |
| D9 | Size of a file | One file per month. The calendar goes back as far as month files exist. Confirmed after the review had counted what it costs. |
| D10 | Bucket's name | In `config.yaml`. |
| D11 | Undoing | `sm data unpublish` removes the files and leaves the database as it was before `sm data publish` was run. Asked for by the author after reading the design. |
| D12 | Guard | Both commands refuse a folder that holds files this database never uploaded, unless `--force` is given. Proposed by Claude, accepted by the author. |

**One decision changed along the way.** D6 first said that a key change replaces the files
by itself, and that Stamind deletes the old ones. With one file per month that no longer
holds: the older months do not fit in a command's 3 seconds. So after a new token the
operator runs `sm data publish` once (§9).

**Decided without asking the author, open to objection.**

- A command uploads only from a database that `sm data publish` published (§6, step 1).
  The review had proposed to keep the bucket's name in the database for the same purpose.
  The author chose the config file, and this rule gives the same protection.
- Only the two commands of §9 delete files.
- `sm data unpublish` deletes the index file first, and asks for no confirmation.
- The older months are rebuilt by the operator, with `sm data publish`. Rebuilding them
  without him was weighed and left out (§16).
- The page draws at once from the button, then again from the files.
- The stamp shows the later of the button's time and the index file's.
- The command is named `sm data publish`.
- The three checks that reading works, that the content is fresh and that listing is
  refused are part of `sm data publish`.

## 15. What was verified, and what was not

**Read in Google's documentation on 2026-09-27.** Every page is under
`https://docs.cloud.google.com/storage/`, except the prices.

| Fact | Page |
|---|---|
| The address of §5 always answers a page from another site. The plain address does not, unless the bucket has a rule for it. | `docs/cross-origin` |
| One request uploads a file and sets "do not cache": a `PUT` on the plain address with the header `Cache-Control: no-store`. | `docs/xml-api/put-object-upload` |
| A public file is served from a cache for an hour, unless the file says "do not cache". | `docs/metadata`, `docs/caching` |
| After a file is replaced, a download returns the new content at once, as long as nothing caches it. | `docs/consistency` |
| `Storage Legacy Object Reader` lets its holder download a file by name and not list. `Storage Object User` lets the service account upload, replace, list and delete. | `docs/access-control/iam-roles` |
| Whoever may download a file may also read its size and the time it was last written. | `docs/access-control/making-data-public` |
| A new bucket made in the console has "Enforce public access prevention" ticked. | `docs/public-access-prevention` |
| A replaced or deleted file is kept seven days, billed, and cannot be downloaded. | `docs/soft-delete` |
| One write per second to one name. | `quotas` |
| The free allowance covers `us-east1`, `us-west1` and `us-central1` only. An upload costs $0.005 per thousand. | `https://cloud.google.com/storage/pricing` |

Two of these were also observed with `curl` on a public bucket of Google's: the address of
§5 sent the header for `https://jlehen.github.io` with no rule on the bucket, and the plain
address sent none.

**Measured on the test copy of the author's database:** building four whole months takes
52 ms, against 43 ms for the ten weeks; one pass over a whole year takes 157 ms; September
with its workout texts is 15.6 KB once compressed; the whole keyboard is 8,846 bytes today.

**To be tried on a real bucket, before the guide is written:**

- that Google's console offers the role `Storage Legacy Object Reader` for everyone. If it
  does not, step 3 of the guide needs one command of Google's command-line tool;
- that a file stored with "do not cache" arrives fresh straight after it was replaced, on
  the address of §5;
- how long an upload takes, from which the 3 seconds of §6 are fixed.

**Not verified:** the download time from a phone on a mobile network; that Telegram's own
browser runs the recipe of §5, which is a web standard and was not tried inside Telegram.

## 16. Not handled

- **A failed upload.** The older file then wins over a newer button, and the stamp is too
  new, until the next command uploads again.
- **A month older than the window** is rebuilt only by `sm data publish`. Until then it
  keeps the data and the words of its last build. An activity that Garmin delivers a month
  late is one example.
- **Rebuilding the older months without the operator.** Stamind cannot see that an old
  month is out of date without building it. If the command is forgotten twice, the next
  step is to let the bot's scheduler run it once a night.
- **A month before the list of mesocycles** has grey strips and an empty legend (§4).
- **A leaked button address.** Its holder reads both pages, every month, as they change,
  until the bot token is revoked. The page key lives as long as the token.
- **The site that serves the pages.** Whoever can publish to it can read the page key of
  every athlete who opens a page. An operator trusts that site.
- **A copy of the live database run under the live config** writes over the live files.
  The test bot is safe, because it has its own token.
- **A file swapped for another inside the bucket.** Only the service account can write
  there, and each day carries its own date, so the month draws empty.
- **Midnight.** Until the first command of the day, a page shows yesterday as today. It
  does so today.
- **Two commands in the same second.** Google allows one write per second to one name. The
  second upload fails, and the next command uploads again.
- **Keeping Google's token between commands.** Each command that uploads asks Google for
  one. Measure first.
- **Writing more than 4,096 bytes from a page**, and editing a session from the calendar.
  The tunnel of §3 is the answer that day.
- **A browser too old** for the functions of §5. The page then behaves as today.
- **Expert mode in Telegram**, which has no keyboard and so no button.
