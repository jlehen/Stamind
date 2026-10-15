"""The `bot` command family: CLI support for the Telegram companion mode.

Hidden maintenance commands the Telegram bot spawns, never typed by the athlete
(DESIGN_bot_simple_frontend.md §4.2, §5.3, §12). Three shapes and no fourth (§12.1): a
**view** runs fixed argv, a **picker** lets the athlete's tap choose the row, a
**capture** reads values out of the message. An operation that fits none of them belongs
to the expert vocabulary — which is why nothing here reaches `plan generate`, a wipe, a
model role or `restart`.

`views` holds the views and the two messages the bot sends unasked, `route` the intent
classifier, `extraction` what every capture's model call shares, `capture` the note inbox
and the dispatch between the intents, `goal` the new goal (the `new_goal` kind), `setting`
the setting change (the `change_setting` kind), `edit` the two intents that change a row
the athlete already has (the `edit` and `pick` kinds), `test_result` a fitness-test result
read into `benchmark record` and the morning-after question that asks for one
(DESIGN_benchmark_from_chat.md), `hand_off` the two questions whose "Yes" starts the coach
beside the chat (`pass_to_coach`, `adjust_week`, DESIGN_long_runs_beside_chat.md), and
`parser` the argparse tree. `bot queue` acts on a tap on a queued item; its handler lives in
`cli/queue_commands.py` with the `queue` commands (DESIGN_athlete_queue.md §6.2).

Four imports in this package stay inside the function that uses them: the three reads of
the OpenRouter client, and the one read of `coach.engine.notes`. `stamind_cli` imports
this package's parser, so hoisting any of them puts `requests` on the startup path of
every command (ARCHITECTURE.md §14). Every other import here is at the top of its file.
"""
