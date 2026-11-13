# Design: the Progress page

**Status:** Built · **Date:** 2026-11-12 · **Branch:** `worktree-progress-page-design`

## 1. The problem

It is Thursday 12 November. The athlete taps "✅ Done lately" in the chat. Seven day lines come
back, then a paragraph about the week of 2 November: 82% of its riding, 1 of its 2 gym
sessions, and the two sessions the coach changed, each with its reason. Two questions share one
screen: "what did I do each day?" and "did my week get what was written?"
(DESIGN_week_as_written.md §5). On a phone it does not read.

Then the athlete taps "📈 Progress". Three sentences come back ("Fitness is holding steady…",
the hours of last week and of this one) and one image of two charts. The top chart has three
lines named CTL, ATL and TSB, the code's names for fitness, fatigue and form. The bottom chart
pairs a planned bar and a done bar per week, under mesocycle names cut short ("Aerobic Re-base &
SIT K…"). Half the width is the six weeks still ahead, so the weeks lived are squeezed into the
left half. The image has a fixed size, so its text is small on a phone, and nothing on it can be
tapped.

What the athlete wants to see is there, but not readable, and not in one place: the weeks as
written are under "Done lately", and a mesocycle's record is read in full only in the terminal
(`plan retrospective`); the chat sees its one sentence.

## 2. The rule

In the chat, one sentence each:

- **"✅ Done lately" is your days.** One line per session, ✅ or ❌, and the count, as it was
  before the week grade.
- **"📈 Progress" is your weeks and your mesocycles, on a page.** It opens a page with four tabs:
  Fitness, Weeks, Mesocycles and Intensity.

In the terminal the split is the same: `workout compare` is the days, `sm progress` the weeks
(§6).

## 3. The page

`miniapp/progress.html`, beside the Calendar and "Goals & plan". It opens on the Fitness tab
and a time span of 3 months. Four tabs across the top, and under them the time span: 4 weeks,
3 months, this plan, everything. Switching either redraws the page at once, with no trip back to
the bot: the file holds the whole history (§4).

```
[ Fitness | Weeks | Mesocycles | Intensity ]
[ 4 weeks · 3 months · This plan · Everything ]
```

"This plan" is the plan that governs today (`get_governing_macrocycle`), from its first
mesocycle's start to its last one's end, or to the last day with a session written when that
comes first; with no plan, the span is not offered. The span picks what every tab lists: the
weeks and the records it overlaps. The page takes today from the file, never from the phone,
and shows the file's stamp under the tabs, as the other pages do: on Monday at 07:00, before
any command has run, it draws Sunday evening's file as it is, and the first command of the day
replaces it. When the file cannot be read, the page says
"Your progress could not be loaded. Close this page and tap again in a moment.", as the details
page does (`miniapp/details_logic.js`).

The page is read-only: it changes nothing, like the Calendar (DESIGN_calendar_miniapp.md §1).

### 3.1 Fitness

One chart, drawn by the page in its own code (§4.3), as wide as the phone:

- **Fitness (CTL) and Form (TSB)**, named so (D7). A line under the chart says what they are:
  "Fitness: what your last six weeks of training built. Fatigue: what your last week or so
  cost. Form: fitness minus fatigue; above zero you are fresh." A button over the chart,
  "Fatigue (ATL)", shows or hides the fatigue line; it is hidden when the page opens, and
  its key reads "Fatigue (ATL), about fitness − form" (choice 3, D11).
- **One pair of bars per week** under it: planned and done, with the hours done over each. For a
  week that has ended, planned is its written week (DESIGN_week_as_written.md §4), as `sm
  progress` already reads it; for the week under way, the planned figure `sm progress` compares
  it with (`week_plan_denom`, `week_plan_seconds`).
- **The mesocycles** as bands, each named in full under the chart, and the goals as marks. The
  bands are the ones `sm progress` draws (`timeline.meso_bands`): the governing plan's mesocycles
  and those `data bootstrap` inferred, whose names start with `~`.

Under 4 weeks and 3 months the chart ends with next week. Under "This plan" and "Everything" it
runs to the last session written, so the fitness projected on the goal's day shows when the
sessions are written that far (choice 2).

### 3.2 Weeks

One line per week, newest first. The week under way comes first, with its hours so far and no
grade: only a week that has ended is graded (DESIGN_week_as_written.md §2). The athlete's weeks
on 12 November:

```
This week so far: 1h24
2 Nov:  🚴 82% · 🏋️ 1 of 2  ▸
26 Oct: 🚴 108% · 🏋️ 1 of 2  ▸
19 Oct: 🚴 132% · 🏋️ 1 of 2  ▸
12 Oct: 🚴 164% · 🏋️ 1 of 2  ▸
```

A short sport is amber, never red: a drop is not a miss (DESIGN_week_as_written.md D3). A tap
on a week opens it in place, with the lines the terminal prints for it (§6):

```
🚴 cycling: written 190, done 156 (82%), short
   Sat 7 Nov Easy Gravel Ride (Deload): cut from 120 to 40 min, moved to Sun 8 Nov,
   changed Sun 8 Nov: "Your resting heart rate is raised after Friday's illness…"
🏋️ strength_training: written 2 sessions, done 1, short
   Fri 6 Nov Full-Body Strength (Deload, Light): replaced by Rest Day — Unwell, …
```

A week with nothing written, before Stamind, is not listed.

### 3.3 Mesocycles

One card per mesocycle record, newest first, a plan's record among them
(DESIGN_cycle_retrospective.md §6). Each card holds the name, the dates, how it ended, the
record's first line (`cycle_records.numbers_line`) and the coach's sentence. The companion's
record of 25 October:

```
Race-Specific Sharpening, 25 Oct – 3 Nov, cut short by a new plan
Sessions 5 of 9 · load 237 of 275 TSS · 5h51 · fitness 16 -> 18 · no test
"You kept your runs going strong and got a good hike in…"
```

A tap opens the whole record, and under it the athlete's own answer when there is one. The
record's lines are shown as the retrospective writer wrote them for `plan generate`: in the third
person, with numbers (choice 15).

A record is created blank the day after its mesocycle ends and written up to seven days later
(DESIGN_cycle_retrospective.md §3), so every mesocycle has such a week. A record not written yet
shows its name, its dates and "not written yet", the terminal's words
(`cli/common.py:print_retrospective`). The mesocycle under way has no record yet: its card comes
from the plan that governs today and shows its name, its dates and "under way". Neither card has
numbers: the Weeks tab shows those weeks.

### 3.4 Intensity

One chart per sport, and a toggle over them: "By week · By mesocycle" (D9). Every sport of the
profile's `sport_preferences` that has zone data in the history has a chart, in the profile's
order, under every span (choice 16). The terminal's rule that a sport must hold a tenth of the
window's time is not applied: it keeps a terminal table short, and a page scrolls. Each sport is
drawn in heart-rate or in power zones as its last 8 weeks say. That is the choice a bare `sm
progress intensity` makes, and the one `workout generate` prescribes in, so the weeks ahead show
what was prescribed. A sport with no zone data in those 8 weeks takes the choice of its whole
history. A sport's zones are the same under every span and in both grains.

- **By week**: each week's time in zone, a bar split by zone, measured behind today and
  prescribed ahead of it. It holds what `sm progress intensity` prints for those sports and what
  the dashboard's `/api/zones` serves: the same marks for a week trained but not recorded and for
  a week planned in the other currency (DESIGN_intensity_distribution.md §9.6, §9.8). The time
  span picks the weeks.
- **By mesocycle**: one bar per mesocycle, its average week in each zone over its completed
  weeks, with the mesocycle's focus under it on a tap. The rates are the ones `sm progress
  intensity --mesocycles` reports, computed by the same Python code (§10), over the same
  mesocycles: the governing plan's and the previous goal's. The time span picks the mesocycles
  it overlaps. The terminal shows one sport; the page one chart per sport.

It is the largest part of the page's code, so it is built last (§9).

## 4. The file

### 4.1 What it holds

One file in the bucket, label `progress`, beside the month files, the index, the plan and the
proposal (DESIGN_miniapp_storage.md §4):

| Key | What |
|---|---|
| `v`, `at`, `today` | As the plan file: the pages' version, the stamp, and the day the file was built |
| `days` | Each day from the first activity to the last day written: date, load, whether actual or planned, fitness, fatigue, form |
| `weeks` | Each week: Monday, planned, done, hours planned and done, mesocycle, under way or ahead; for a week that has ended, its grade per sport, with the lines of §3.2 and each sport's percentage as `percent` gives it |
| `records` | Each record: name, dates, how it ended, first line, the coach's sentence, the whole text, the athlete's answer |
| `zones` | For each sport of §3.4: its zones' names, each week's time in zone as `/api/zones` gives it, over every week, and its rates per mesocycle |
| `goals`, `mesocycles` | The marks and the bands of the chart |

Numbers go in exact, and the page rounds them, but for two it must not work out itself: a week's
planned figure is `week_plan_denom`'s, and a grade's percentage is `percent`'s, rounded down so a
short week never reads 85% on the page and 84% in the terminal. Words go in as the Python
functions the terminal uses build them (choice 9), unwrapped as every page file
(DESIGN_miniapp_storage.md §4): the week's lines from `sport_line` and the line of one changed
session, which `week_grade_lines` wraps only for the terminal and the prompts; the record's first
line from `cycle_records.numbers_line`. A wrapped line in the file would differ between a command
the chat starts (width 900) and one the scheduler starts (width 80), and the file would go up at
each change of hands.

On the athlete's history, the `days` alone are 39 KB of JSON, about 10 KB once compressed.

### 4.2 When it goes up

As the other files: rebuilt after every command, and uploaded only when its content changed since
the last upload (DESIGN_miniapp_storage.md §6). That is the "upload it ahead of time" the
athlete asked for. Its content changes when a Garmin pull brings an activity or a morning's
metrics, which moves fitness and form; when the schedule changes, which moves the planned bars
and the projection ahead; and when a record is written. On a Tuesday with a morning pull, a
morning `workout adapt` that changes Thursday, and a ride that reaches Garmin at 18:00, it goes
up three times, about 29 KB each (measured, below). On a day with nothing new, the commands
that run rebuild it, find it unchanged, and upload nothing. `sm data publish` uploads it with
the rest.

Building it costs every command, and a typed message pays it twice: `sm bot route`, which reads
what the message means, is a command of its own. On 12 November, on the athlete's database, the
timeline took 84 ms and grading every week 640 ms. The 640 ms is `graded_weeks` scanning every
session and every activity again for each week, parsing each date each time; sorting them into
weeks once should bring it near the 84 ms. Measured again once built, on a copy of the
athlete's database of 12 November: grading every week takes 60 ms, and the whole file, Intensity
included, 160 ms (§12). The file is 197 KB of JSON, 29 KB once compressed: the days 13 KB, the
zones 12 KB, the weeks 4 KB.

### 4.3 No outside script

The page key travels in the button's address (DESIGN_miniapp_storage.md §8). A chart library
loaded from another site would run with access to it. So the page loads nothing but its own
files and Telegram's script, as every page does, and draws its charts as SVG in its own code.

## 5. The chat

- **"📈 Progress" becomes a page button** on an instance whose pages are published
  (`page_files.pages_published`: a bucket is configured and `sm data publish` has run), like "🗓
  Calendar" and "🎯 Goals & plan". It carries no snapshot, only the page's address and the
  bucket's three values, about 180 bytes. The keyboard's worst case was 9,579 bytes of the 9,921
  Telegram accepted (DESIGN_miniapp_storage.md §8), which would leave 162 bytes, and a keyboard
  over the limit gets no reply at all. So `calendar_page.BUDGET_BYTES` drops by 256 to pay for
  the progress button, and the keyboard's worst case does not grow. The calendar's address then
  carries about one day sheet fewer, at the far end of its window. Where the pages are
  published the sheets come from the file anyway.
- **Where the pages are published, a typed "how's my progress?"** is answered with "Open 📈
  Progress below to see how your weeks went.", like a typed question about the week or the plan
  ([ARCHITECTURE.md §15](../docs/ARCHITECTURE.md), "The multi-day schedule, goals, and plan live
  on their pages alone").
- **What goes from the chat:** the week paragraph under "✅ Done lately", and the three sentences
  of "📈 Progress" with the code that wrote them. `progress` in the chat prints what the terminal
  prints, as `/plan show` does.
- **An instance whose pages are not published** keeps "📈 Progress" as a command button. It runs
  `progress --chart` as today, which now prints the terminal's table and the image. Both
  instances of today are published.
- **The welcome card** says "📈 Progress — how your weeks and mesocycles went".

## 6. The terminal

`sm progress` takes the view as a word, one per tab (choice 13):

| Page | Terminal |
|---|---|
| Fitness | `sm progress fitness`, or a bare `sm progress`: the fitness line, the goals and the weekly load table, as today; `--chart` still writes the image, `--explain` still adds the footnotes |
| Weeks | `sm progress weeks`: one line per week that has ended; `sm progress weeks DATE` that week in full |
| Mesocycles | `sm progress mesocycles`: every record, newest first, as the tab shows them |
| Intensity | `sm progress intensity [SPORT…]`: the weekly zone tables, as `-z` printed them; `--mesocycles`, `--hr` and `--power` as before |

`-w N|all`, the weeks either side of today, stays and applies to every view but mesocycles.

The word is not required. A bare `sm progress` is the Fitness view, as the page opens on Fitness
(choice 1): `progress` joins `settings` and `queue` as a group that acts bare
(DESIGN_cli_noargs.md §a3, which the build amends). The old spellings go, with no alias:
`sm progress running` becomes `sm progress intensity running`, and `-z` goes with them (AGENTS.md:
no backward compatibility, the author operates every instance). `sm progress weeks 12` and `sm
progress mesocycles`, the forms without dashes of `-w 12` and `--mesocycles`
(`cli/argparse_ext.py`), now name the views.

A flag goes after the view's word: `sm progress weeks -w 12`. A bare `sm progress` also takes
the Fitness flags, so the operator's `sm progress -w 12` and `sm progress --chart` keep working;
the group and `fitness` share one parent parser for them.

`sm progress weeks` prints one line per week that has ended, in the window's order:

```
WEEKS AS WRITTEN
w/c 10-26  cycling 108% · strength_training 1 of 2, short
w/c 11-02  cycling 82%, short · strength_training 1 of 2, short
```

`sm progress weeks 2026-11-02` (any day of that week) prints that week in full: each sport
against what was written, and under a short sport the sessions no longer as written, with the
day and the reason of the change. Those are the lines `workout compare` printed for a week since
11 November, and it prints them no longer.

`sm progress mesocycles` prints the records as `plan retrospective` prints one goal's, every goal
at once and newest first, through the same renderer. `plan retrospective` stays: it lays one
goal's records out as that goal's plan.

`workout compare` is the days again, and its closing line says "Great adherence!" again when no
day has a discrepancy: it went because the week below could be short, and the week is no longer
below it (choice 14).

## 7. Choices made without asking

The author rules on each. A review may object in the last column; it may not remove or change
a choice.

| # | Choice | Why | Chosen over | Review |
|---|---|---|---|---|
| 1 | The page opens on Fitness and 3 months; the spans are 4 weeks, 3 months, this plan, everything (§3) | 3 months holds a mesocycle and its neighbours; the default of `sm progress` is 8 weeks either side | Opening on Weeks; other spans | Kept by the author (D6) |
| 2 | Under 4 weeks and 3 months the chart ends with next week; under this plan and everything, at the last day written (§3.1) | Today half the chart is the future; the projection at the goal still shows under the plan | The future always to the last day written | Kept by the author (D10) |
| 3 | The chart shows fitness and form; a button shows fatigue too, hidden when the page opens (§3.1) | Fatigue is the noisy line, and form already carries it | All three lines always | Ruled by the author: a button, with the key "about fitness − form" (D11) |
| 4 | Fitness and form are named so, with the code's name in brackets: "Fitness (CTL)", "Form (TSB)" (§3.1) | CTL, ATL and TSB alone mean nothing to the athlete | The code's names alone | Kept, with the brackets added by the author (D7) |
| 5 | Weeks lists newest first, the week under way first with its hours and no grade (§3.2) | The week the athlete asks about is the last one | Oldest first, as the terminal table | Kept by the author, to try (D6) |
| 6 | A week's sessions open on a tap, in place (§3.2) | Every week of the athlete's last five has a short sport; listing them all is long | Every short week open | Kept by the author (D6) |
| 7 | Mesocycles shows every record, a plan's included, newest first; the one under way has no numbers (§3.3) | The records are few; numbers for a mesocycle under way would be a second computation of what Weeks shows | Only the active goal's records; numbers so far | Kept by the author (D6) |
| 8 | Intensity by week and by mesocycle, one at a time, with a toggle (§3.4) | Two grains, two questions: when did it change, and did the mesocycle do what it said | By week only | Changed by the author from "by week only" (D9) |
| 9 | The file carries the terminal's words, built in Python (§4.1) | One wording for one fact; the page formats only numbers | Words built in the page's code | Kept by the author, who sees no benefit in a second wording (D8) |
| 10 | The file is built after every command, as the others, and uploaded when it changed (§4.2) | The step and its fingerprint exist; no schedule to add | Building it only after a pull | Kept by the author, once told when it uploads (D10) |
| 11 | The page draws its charts as SVG in its own code (§4.3) | The page key is in the address | A chart library from another site | Kept by the author (D6) |
| 12 | A typed question about progress gets a pointer only where the pages are published (§5) | Elsewhere there is no page to point at | A pointer everywhere | Kept by the author (D6) |
| 13 | `sm progress` takes the view as a word (`fitness`, `weeks`, `mesocycles`, `intensity`), not required: bare is Fitness; `weeks DATE` is one week in full (§6) | One word per tab, as the page; the flags of today add sections to one view and would not say which of four is shown | Flags on one view (`--week DATE`, `-z`); the word required | Revised after the author's question "an option, or a mandatory argument?", then kept (D10) |
| 14 | "Great adherence!" comes back to `workout compare` (§6) | It went only because the week grade sat below it | Leaving it out | Kept by the author (D6) |
| 15 | A tap on a record shows its lines as the retrospective writer wrote them for `plan generate`, third person and with numbers; DESIGN_cycle_retrospective.md §8 ("No view of the plan shows it") is amended (§3.3) | The record is the mesocycle's whole story, and the page is where the athlete looks back | The card with the coach's sentence alone, no tap; asking the writer for a second text | Made during the review (thorough) |
| 16 | Intensity shows every sport of the profile that has zone data, under every span; each in the zones its last 8 weeks say, or its whole history's when those weeks hold none (§3.4) | Chosen over the whole history, a power meter bought in September leaves cycling in heart-rate zones while `workout generate` prescribes in power, and every week ahead reads "planned in the other currency". Chosen over the weeks shown, a new sport or one stopped ten weeks ago has no chart | The terminal's rule over 8 weeks (a new sport has no chart); every sport and its zones over the whole history (the weeks ahead lose their prescribed bars) | Made during the review, from both reviewers |

## 8. Not handled

- The bars are not split by sport. A missing gym session shows in the Weeks tab, not on the
  chart.
- Tapping a bar opens nothing.
- The page does not remember the last tab or span: it opens on Fitness and 3 months.
- The dashboard keeps its image (`/api/timeline.png`) and its own zone tables.
- The file has no bound. Its days grow by about 10 KB a year once compressed, more with the
  weeks' reasons.
- A sport that is not in the profile's `sport_preferences` has no Intensity chart, as in the
  terminal. A sport in it with one recorded activity has a chart that is nearly empty.
- A sport's weeks from before its zones changed, such as rides before a power meter, show the
  "trained but not recorded" mark.
- A tap on the old keyboard's "📈 Progress", before the bot's next message brings the new
  keyboard, prints the terminal's fitness view once.
- Intensity by mesocycle covers the governing plan and the previous goal's, as the terminal
  does; under "Everything" no older mesocycle has a bar.
- The opened week shows the terminal's words to the companion athlete as they are:
  "strength_training", "written 190, done 156" with no unit (D8).
- An opened record shows the companion athlete lines written about her for `plan generate`, in
  the third person, which may open with a miss: "The athlete completed 5 of 9 sessions…". The
  rules her own sentence follows (DESIGN_cycle_retrospective.md §8) do not apply to them
  (choice 15).

## 9. Build order

Two landings. The first holds steps 1 and 2, so the chat is never without the weeks; the second
is step 3, which is owed: without it the page has three tabs and D3 and D9 are not met.

1. **Days and weeks apart.** "✅ Done lately" loses the week paragraph, `workout compare` loses
   its weeks section and gets "Great adherence!" back, and `sm progress` takes its four words.
2. **The page, without Intensity.** The file, its place in the step after every command, the
   Fitness, Weeks and Mesocycles tabs, the keyboard button, the pointer, the welcome card's line
   and the chat's Progress sentences removed; `graded_weeks` sorted into weeks once.
3. **Intensity.** The `/api/zones` body moved where the file and the dashboard both call it, the
   per-mesocycle rates added to the file, and the tab with its toggle. A file with no `zones`
   shows the tab's empty state, the one an athlete with no zone data sees.

## 10. Code

- **`analytics/written_week.py`**: `graded_weeks` sorts the sessions and the activities into
  weeks once (§4.2); the unwrapped line of one changed session is split out of
  `week_grade_lines`, so the file and the terminal share it; the one-line week of `sm progress
  weeks` ("w/c 11-02  cycling 82%, short · …") is a function beside `sport_line`.
- **`cli/progress.py`**: the four words, a bare run as `fitness` with the Fitness flags on the
  group's parser as well; `weeks` with its optional DATE; `mesocycles` through
  `cli/common.py:print_retrospective`, which already prints a blank record as "not written yet";
  `intensity` takes the sports, `-z` goes. DESIGN_cli_noargs.md §a3 names `progress` as the third
  group that acts bare. **`cli/workouts/compare.py`** and **`cli/render/companion.py`**: the
  weeks go, and "Great adherence!" comes back. **`cli/render/session_lines.py`**:
  `simple_week_grade_lines` goes. **`cli/render/plan_lines.py`**: `simple_progress_lines` and
  `simple_week_hours_line` go, with `CompanionRenderer.progress`, so `progress` in the chat is
  the terminal's (§5).
- **`cli/render/progress_page.py`**, new: the file's content (§4.1) and the page's address, as
  `plan_page.py` is for "Goals & plan". It imports `timeline_rows` inside its function, as
  `cli/progress.py` does, so no command loads the Garmin package at start.
- **`cli/render/calendar_page.py`**: `BUDGET_BYTES` drops by 256, its comment naming the
  progress button (§5).
- **`page_files/sync.py`**: `build` adds the file, `rebuilt` and the upload order name it, last.
- **`chat/app.py`** (`_page_buttons`), **`chat/keyboards.py`** (`simple_keyboard_rows`,
  `SIMPLE_WELCOME`): the page button in place of the command button, when the pages are
  published, and the welcome card's line. **`chat/routing.py`**: the pointer for
  `show_progress`, under the same condition.
- **`miniapp/progress.html`, `progress.js`, `progress_logic.js`**: the page, its drawing, and its
  pure logic under node tests (`miniapp/tests/`), reading the file through `storage.js`.
- **The zones** (step 3): the body of `stamind_web.get_zones` moves into a function in
  `analytics/intensity.py`, which both it and `progress_page.py` call, so the dashboard and the
  page cannot disagree; the dashboard may not load `stamind/cli/` (ARCHITECTURE.md §14). It
  takes the weeks to draw, the sports and, optionally, the weeks to choose each sport's zones
  from; the file passes every week and the 8 weeks either side of today, the dashboard one list
  as today. The per-mesocycle rates come from `mesocycle_report.measured_window` and
  `intensity.zone_rows`, the two functions `mesocycle_report` prints them from, over one read of
  the activities (`get_completed_activities()`), sliced per mesocycle and sport;
  `mesocycle_report` does not change.
- **Docs**: `docs/ARCHITECTURE.md` (the module lines, the keyboard, the `progress` and `workout
  compare` rows, §15's pages entry, §17); DESIGN_miniapp_storage.md §4 gains the file's row;
  DESIGN_week_as_written.md §5 points here for where the weeks are shown;
  DESIGN_cycle_retrospective.md §8 and §15 ("The sentence outside the reply") point here
  (choice 15).

## 11. Tests

- `sm progress`: bare is `fitness`; `weeks` lists the ended weeks of the window only, the week
  under way never graded; `weeks DATE` one week in full; `mesocycles` every record newest first;
  `intensity running` the old `progress running`.
- `workout compare` and "✅ Done lately": no week section; "Great adherence!" when no day has a
  discrepancy.
- The file: the keys of §4.1; an ended week's grade; a record with and without the athlete's
  answer; built after a command and uploaded only when it changed.
- The keyboard: the page button when the pages are published, the command button when not, and
  the keyboard's addresses under the budget of DESIGN_miniapp_storage.md §8.
- The typed question: the pointer where the pages are published, `progress --chart` where not.
- Intensity: a sport of the profile recorded only before the last 8 weeks has a chart; a sport's
  zones are those of its last 8 weeks.
- The page's logic under node: the spans, the chart's end (choice 2), the week lines, the
  intensity toggle.
- The per-mesocycle rates, on a fixture of two mesocycles with known minutes.
- The file is the same built at a width of 80 and of 900; a record not written yet builds a
  card; the page draws the file's today, not the phone's.

## 12. After landing

The page goes live when main is pushed (`.github/workflows/pages.yml`). On each instance, one
command (`sm status`) runs before its bot is restarted, so the file is up before the new keyboard
is: `/start`, `/help` and the reply to `/restart` send the keyboard with no command behind them.
Both bots are restarted, since the keyboard is built in the bot. No `sm data publish` is needed.
The build of the file is timed once on each instance, and its cost written here. On a copy of the
author's database of 12 November, before landing: 160 ms for the whole file (the timeline 82 ms,
grading every week 60 ms), 29 KB compressed. On copies of 13 November: the author's 182 ms
and 28 KB, the companion's 86 ms and 13 KB.

## Decisions Log

| # | Topic | Decision | Why | Source | Date |
|---|---|---|---|---|---|
| D1 | Where progress is shown in the chat | A page with tabs replaces the chat's text and image | One view, readable on a phone, quick to switch | Athlete | 2026-11-12 |
| D2 | How the chart reaches the page | The page draws it from the numbers in its file | It fits the phone, the span switches at once, and no command pays for drawing an image | Athlete | 2026-11-12 |
| D3 | Which tabs | Fitness, Weeks, Mesocycles and Intensity, all four | No reason found to leave one out | Athlete | 2026-11-12 |
| D4 | "✅ Done lately" | The days alone, as before the week grade | The week paragraph made it unreadable | Athlete | 2026-11-12 |
| D5 | The weeks in the terminal | They move from `workout compare` to `sm progress` | The same split as the chat: compare the days, progress the weeks | Athlete | 2026-11-12 |
| D6 | Choices 1, 5, 6, 7, 11, 12 and 14 | Kept as written; 5 "to try" | | Athlete | 2026-11-12 |
| D7 | The names on the chart | "Fitness (CTL)", "Form (TSB)": the plain name, the code's in brackets | Choice 4, with the brackets added | Athlete | 2026-11-12 |
| D8 | One wording | The page shows the words the terminal prints | Choice 9; no benefit seen in a second wording | Athlete | 2026-11-12 |
| D9 | Intensity's grains | By week and by mesocycle, one at a time, a toggle between them | Choice 8 changed: both, not by week only | Athlete | 2026-11-12 |
| D10 | Choices 2, 10 and 13 | Kept: the chart's future by span, the file uploaded when it changed, `sm progress` with a view word that is not required | | Athlete | 2026-11-12 |
| D11 | Fatigue on the chart | A button shows or hides the fatigue (ATL) line, hidden at first; its key says it is about fitness minus form | Choice 3 settled | Athlete | 2026-11-13 |
