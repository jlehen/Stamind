# Mini app storage: checkpoint of the design interview

**Status:** Interview interrupted, one question open · **Date:** 2026-09-27 ·
**Branch:** worktree-miniapp-storage, at `a147df9`, no commit of its own

This file is a checkpoint, not a design. It holds what was decided, what was measured and
what is still open, so that a new session can write `designs/DESIGN_miniapp_storage.md`
without asking again. The session that ran the interview lost several replies, so the last
answer it owed the author is written here in full (§5).

## 1. The problem

A mini app is a web page opened inside Telegram. Stamind has three: the gym logger, the
calendar and "Goals & plan". Each gets its data in the address of its button, after the `#`.

Two limits hold the pages back:

- **Data going in.** Telegram refuses a reply keyboard above about 9.9 KB, all buttons
  together. The calendar has 5 KB, "Goals & plan" 2 KB, the gym button up to 1.9 KB. With
  the workout texts, the calendar's ten weeks would need about 47 KB
  (DESIGN_calendar_miniapp.md §5, §8).
- **Data coming out.** A page sends one message of at most 4,096 bytes with `sendData`, and
  Telegram closes the page when it does.

The author's need is the first limit: get more data into the pages. Writing more than 4 KB
back is not needed today.

## 2. How the choice was reached

The author's criteria were ease of setup for whoever installs Stamind, little maintenance,
decent latency, and room for later features. Ease of setup weighed most: Stamind used to
need a repository, a config file, a Telegram bot and a Google service account, and a web
server with a certificate and a firewall rule was judged too much to ask.

One rule decides what is possible. A mini app is a web page loaded over HTTPS, so it can
only call HTTPS on a named host that holds a valid certificate. It cannot open a TCP
connection, and the browser blocks a call to plain HTTP whatever the payload is. So somebody
must hold a certificate, and the options differ by who.

| Option | Why it was not chosen |
|---|---|
| Stay inside Telegram | The limit stays. Telegram's storage for pages is written by the page only, never by the bot. |
| Own domain and web server | Too much setup for an operator, and it does not work behind a home router. |
| A tunnel (Tailscale Funnel) | Works, and stays the answer the day a page must write more than 4 KB. Not needed for reading. |
| A message service (pub/sub) | Carries messages, not questions and answers. Google's own Pub/Sub is meant for servers, not for pages. |
| A rented function as middleman | A second program at a provider, and the data in two places. |
| Plain HTTP or TCP with own encryption | Blocked by the browser. The encryption idea was kept, the transport was not. |
| **Encrypted files in a storage bucket** | **Chosen.** Nothing runs on the operator's machine, and no door opens onto the database. |

The author chose Google Cloud Storage because the operator already has a Google project and
a service account, made for Google Calendar.

## 3. What was decided

Every row was answered by the author in the interview, except where the last column says so.

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Provider and cost | Google Cloud Storage. A payment method is acceptable. The operator picks the region. | The operator already has the project and the credential. Stamind only needs the bucket's name. | Interview | 2026-09-27 |
| D2 | What the file holds | The whole snapshot of each page, long texts included. The buttons stay as today and serve as the fallback. The gym logger is untouched. | First answered "long texts only"; widened by D5, which makes the file the main source. | Interview | 2026-09-27 |
| D3 | Storage is optional | With no bucket configured, the pages behave as today. | Follows from the buttons staying as they are. Only an operator who wants the long texts needs a payment method. Stated by Claude, not objected to. | Interview | 2026-09-27 |
| D4 | Chat buttons | "💬 Full day in chat" and "💬 Why, in chat" are shown only when the full text could not be downloaded. | With the text on the page the button repeats it. Without the text it is the way to read it, as today. | Interview | 2026-09-27 |
| D5 | Freshness | The file is uploaded after every command, also one run in the terminal. When the download worked, the page draws from the file. | The page then shows the newest state even when the phone holds an old button. Claude had recommended tying the file to the button; the author chose fresher. | Interview | 2026-09-27 |
| D6 | Key | Computed from the bot token. A key change replaces the files by itself, and Stamind deletes the old ones. | Nothing new to store. A test bot on a copy of the database has its own token, so it can never write over the live files. | Interview | 2026-09-27 |
| D7 | Setup | By hand, from a guide in the README, plus a command that tests the setup and names the step that is wrong. | A mistake in the setup is silent, because the page falls back to the button. The service account gets rights on one bucket only. | Interview | 2026-09-27 |
| D8 | Failures | Each failed upload goes to the journal, and `sm status` shows one line while the last upload has failed. Nothing is sent to anyone. | The athlete is not blocked, so nobody needs to be woken. The operator sees it when they look. | Interview | 2026-09-27 |

**Questions the author asked, and the answers given.**

- *If the key changes, what is the procedure to keep the files valid?* None by hand. The
  file names are computed from the key, so a new key means new names. The next command
  uploads under the new names and deletes the old files. The bot's next message carries the
  new key. In between, the phone's old button finds no file and the page falls back.
- *Why not store the key in the database?* It works, and it is tidier than a file on disk.
  Its drawback is that a copy of the database carries the key. The author runs a test bot on
  a copy of the live database, and with the same bucket in its config it would write over
  the live files. The author then chose the bot token.

## 4. What Claude decided alone, open to objection

These were stated to the author and not objected to. None was asked as a question.

- **One shape for both sources.** The file has the shape of the button's data, with every
  day's sheet and the long texts. The page takes the file when it has it, and the button
  otherwise. There is no merging line by line.
- **The page draws at once, then again.** It draws from the button immediately, and again
  from the file when the file arrives.
- **Upload only when something changed.** After each command Stamind builds the data and
  uploads only when it differs from the last upload.
- **The stamp says when the data last changed.** If nothing changed since 07:02, the stamp
  still says "as of Wed 07:02" at 18:00.
- **Each bot has its own folder in the bucket**, named after the bot's public number, the
  part of the token before the colon. It stays the same when the token is revoked.
- **Old files are deleted by looking, not by remembering.** After an upload, Stamind lists
  its own folder and deletes every file it did not just write. So no record of old names
  can travel to a test bot with a copy of the data. §5 may change this rule.
- **The button's address grows by about 120 characters**: the key, the bucket's name and
  the folder. That comes off the calendar's 5 KB budget.
- **The upload gets 3 seconds**, then gives up until the next command. A command never
  fails because of an upload.
- **The calendar's design document is not rewritten.** The new document states its own
  contract.

## 5. The open question: file names and the size of a file

**What the author said.** "I want to discuss about the file names. I was thinking they
should be idempotent. I don't know what granularity will be the file (per day, per week,
per mesocycle?) but if they keep the same name, then the miniapp always find them, as soon
as they are rewritten. What do you think?"

**Claude's answer, which the session failed to deliver.**

*Stable names: yes.* A file's name is computed from the key and from what the file holds,
never from when it was written. Writing the file again keeps its name. This is what D5
needs, and it is what §4 already assumed. It has one requirement: Google serves a public
file from a cache for one hour unless told otherwise, so each file is stored with a "do not
cache" instruction. Without it, the phone could see the old content for an hour.

*The size of a file.* The page draws one month at a time, and leaves the days of other
months blank (`monthWeeks` in `miniapp/calendar_logic.js`). That decides which units fit.

| Unit | Downloads to draw one month | Verdict |
|---|---|---|
| One file per page | 1, about 35 KB | Simplest. Same shape as the button's data. The calendar stays at ten weeks. |
| One file per month | 1 | Matches what the page draws. Old months stay in the bucket, so the calendar could go back as far as files exist. |
| One file per week | 5 or 6 | Nothing gained over a month, since the page draws a month. |
| One file per day | About 30 | Too many downloads. |
| One file per mesocycle | Varies | The unit is not stable. `plan generate` can rewrite the mesocycles, and then a name no longer stands for the same days. |

*What a file per month costs.* It is more than a change of name:

- The snapshot must be split. The days go into the month files. What belongs to no month
  goes into a small file of its own: today's date, the stamp, the goals, the mesocycles and
  the last day of the schedule.
- After each command Stamind builds the three or four months the ten weeks touch, and
  uploads those that changed.
- The rule "delete every file I did not just write" no longer works, because the older
  months must stay. Stamind would compute the names of every month it has data for, and
  delete only the files outside that list.
- After a key change the older months are gone, unless Stamind builds and uploads all of
  them once. That is a few seconds per year of data.

*Claude's view.* The real question is not the unit. It is whether the calendar should go
further back than ten weeks. If it should not, one file per page is enough, and nothing
else is worth building. If it should, the month is the unit. A file per page today does
not block a file per month later, because the names are computed and a new name can be
added beside the old one.

**The question to ask next.** "Should the calendar go further back than the ten weeks it
shows today?" with these options: no, one file per page; yes, one file per month; yes, but
later, so start with one file per page.

## 6. What was verified

**Google Cloud Storage, from Google's documentation.**

- A bucket needs billing enabled on the project, and the free allowance needs a billing
  account with a payment method.
- The free allowance is 5 GB of storage, 5,000 uploads and 50,000 downloads a month, in
  three regions only: `us-east1`, `us-west1` and `us-central1`.
- Public reading is given by granting `allUsers` a role on the bucket. `Storage Object
  Viewer` also lets anyone list the files. `Storage Legacy Object Reader` lets them
  download a file by its name and nothing else.
- The console's "Enforce public access prevention" box must be unticked on the bucket.
- A public file is read without any credential at
  `https://storage.googleapis.com/BUCKET/NAME`.
- A public file is served with `Cache-Control: public, max-age=3600` unless the file says
  otherwise. `no-store` prevents it.
- A bucket rule can delete files by age. A deleted file is kept seven more days by default.

**Measured from the Stamind server, in Germany, on a Google public bucket hosted in the US.**

- Five downloads of an 8 KB file took between 0.03 and 0.25 seconds.
- The plain address sent no `Access-Control-Allow-Origin` header for
  `https://jlehen.github.io`. A page would be refused.
- The API address,
  `https://storage.googleapis.com/storage/v1/b/BUCKET/o/NAME?alt=media`, sent
  `access-control-allow-origin: https://jlehen.github.io` with no rule set on the bucket. So
  the operator may have no cross-site rule to set.

**Measured on a copy of the test database.**

- Gathering the ten weeks takes 35 to 41 ms, and wording both pages 11 to 13 ms.
- The calendar's data without the workout texts is 31,480 bytes of JSON, and 4,488 bytes
  once compressed. The plan page's is 1,557 bytes, and 788 compressed.

**Browsers and Telegram.**

- `fetch()` from an HTTPS page to an `http://` address is blocked, not upgraded (MDN).
- Chrome's raw socket interface is reserved to installed "Isolated Web Apps".
- Telegram for Android builds the mini app's browser in `BotWebViewContainer.java`, which
  never switches the block off.

**The code, at `82fb499`.** File paths are relative to the repository root.

- Every command runs in a CLI process and passes through `run_once` in `stamind_cli.py`.
  The bot starts commands as processes (`stamind/chat/runner.py`), and so does its
  scheduler (`stamind/chat/scheduler.py`). The bot never writes to the database itself.
- A command that only reads can still change the data, because it pulls from Garmin and
  from Google Calendar first. The pages also change at midnight with no command, because
  today moves. So the rule must be "build after every command, upload when the result
  differs", not "upload after a write".
- The calendar's data is built by `snapshot`, `pack` and `fit` in
  `stamind/cli/render/calendar_page.py`, from the list of days that `gather` in
  `stamind/calendar_days.py` returns. The plan page's is built in
  `stamind/cli/render/plan_page.py`.
- The keyboard is rebuilt for every message part, in `_send_keyed` in
  `stamind/chat/replies.py`, with about 11 database calls and no cache.
- The pages read the address in `packedFromHash` and `snapshotFromHash` in
  `miniapp/calendar_logic.js`. `miniapp/plan.js` reuses them.
- The three page addresses are constants in the code, and both athletes' instances share
  them.
- The Google credentials are built inside `CalendarSyncer.__init__` in
  `stamind/gcal/client.py`, with the Google Calendar scope only. Storage needs its own
  credentials object, built from the same JSON file.
- `google-auth`, `requests` and `cryptography` are installed. `cryptography` is not listed
  in `requirements.txt`. No new package is needed.
- The tests refuse any network connection that is not to the machine itself
  (`tests/__init__.py`, `tests/test_isolation_guards.py`).
- GitHub Pages serves one site for every branch, and the last branch deployed wins.

## 7. What was not verified

- That the API address sends the cross-site header on a bucket of the operator's own.
- How a "do not cache" instruction is set at upload time through each of Google's two
  upload interfaces.
- Whether a page opened from the reply keyboard receives Telegram's signed identity. The
  design does not depend on it.
- The download time from a phone on a mobile network.
- What `plan show --macrocycle N` prints in companion words, which is what the plan page's
  file must hold for "💬 Why, in chat" to become unnecessary.

## 8. Not handled

- **A failed upload.** The older file then wins over a newer button, until the next command
  uploads again.
- **Writing more than 4,096 bytes from a page**, and editing a session from the calendar.
- **Changing the key on a schedule.** Anyone holding a button's address can read both pages
  for as long as the key lives.
- **Expert mode in Telegram**, which has no keyboard and so no button.

## 9. What comes next

1. Ask the question of §5 and record the answer as D9.
2. Offer the red-team pass. Treat each finding as a candidate to reject, and keep only what
   a plausible athlete or operator hits in a real week.
3. Write `designs/DESIGN_miniapp_storage.md` as a contract of its own.
4. Delete this file once the design holds everything it says.

The interview's state, in the form the interview skill reads, is in
`designs/.DESIGN_miniapp_storage.interview.json`.
