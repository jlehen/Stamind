"""How text looks on the way out: colour, width, wrapping and tables.

Nothing here decides *whether* a line is printed — that is `output.py` — and nothing
here knows what a date is. The only app module it reaches for is `trainmate.sentinels`,
deferred inside `asides_enabled`, because the verbosity default depends on which
front-end is driving (DESIGN_output_verbosity.md §2).
"""
import os
import re
import shutil
import sys
import textwrap
from typing import Optional

# ANSI escape codes for terminal coloring
ANSI_ESCAPE = re.compile(r'(?:\033|\x1b)\[[0-9;]*m')
RESET = "\033[0m"


def default_wrap_width() -> int:
    """The column width text wrapping targets, default 80.

    Overridable via the TRAINMATE_WRAP_WIDTH env var so a narrow client (e.g. the
    Telegram bot rendering into a phone-width monospace message) can ask the CLI to
    wrap tighter and avoid the client double-wrapping 80-col lines. Floored at 20."""
    raw = os.environ.get("TRAINMATE_WRAP_WIDTH")
    if not raw:
        return 80
    try:
        return max(20, int(raw))
    except ValueError:
        return 80


def display_width() -> int:
    """How many columns a table may spread over: the real terminal's, else the wrap width.

    `default_wrap_width` is a budget for *prose* — 80 unless a client asked for less — and
    a table that has to fit the screen wants the screen (DESIGN_logging.md §7.2). An
    explicit TRAINMATE_WRAP_WIDTH still wins, because that is a narrow client stating its
    own width. Off a terminal — piped, tested, the bot — it stays the wrap width, so the
    output does not change with whichever window happened to run the command."""
    if os.environ.get("TRAINMATE_WRAP_WIDTH") or not sys.stdout.isatty():
        return default_wrap_width()
    return max(40, shutil.get_terminal_size((80, 24)).columns)


def is_color_enabled() -> bool:
    """Checks if color output is supported and not explicitly disabled."""
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def colorize(text: str, color_code: str) -> str:
    """Wraps text in ANSI escape code if coloring is enabled.

    Any reset already inside `text` re-opens this code, so wrapping a string that
    embeds its own colouring (a red error carrying a cmd(), say) keeps the rest of
    the line in the outer colour instead of dropping it to the terminal default."""
    if not is_color_enabled():
        return text
    return color_code + text.replace(RESET, RESET + color_code) + RESET


def bold(text: str) -> str:
    return colorize(text, "\033[1m")


def dim(text: str) -> str:
    return colorize(text, "\033[2m")


def green(text: str) -> str:
    return colorize(text, "\033[32m")


def red(text: str) -> str:
    return colorize(text, "\033[31m")


def yellow(text: str) -> str:
    return colorize(text, "\033[33m")


def cyan(text: str) -> str:
    return colorize(text, "\033[36m")


def blue(text: str) -> str:
    return colorize(text, "\033[34m")


def magenta(text: str) -> str:
    return colorize(text, "\033[35m")


def gray(text: str) -> str:
    return colorize(text, "\033[90m")


def asides_enabled() -> bool:
    """Whether side information prints: a terminal reads it live, a chat front-end gets
    it as history above the answer. TRAINMATE_VERBOSE=1/0 forces either way — no CLI
    flag, `-v` is taken (DESIGN_output_verbosity.md §2/§4)."""
    raw = os.environ.get("TRAINMATE_VERBOSE")
    if raw:
        return raw.lower() not in ("0", "no", "false")
    from trainmate.sentinels import is_json_frontend
    return not is_json_frontend()


def strip_ansi(text: str) -> str:
    """Drops ANSI colour codes — for surfaces that aren't a terminal (JSON, logs).

    Also puts back any space `keep_whole` marked, so a journal line reads normally
    whether or not it went through the wrap first."""
    return ANSI_ESCAPE.sub("", text).replace(_KEEP, ' ')


def cmd(text: str, *, quote: bool = True) -> str:
    """Renders a command the message is telling the athlete to run, single-quoted.

    Colour-neutral on purpose — bold only — so it comes out as the bright shade of
    whatever colour encloses it: bright red inside an error, bright yellow inside a
    warning. Nest it *inside* the surrounding colour call rather than concatenating
    beside it; colorize() re-opens that colour afterwards, so the tail of the sentence
    keeps it. `quote=False` for a command printed alone on its own line, where the
    quotes are just noise."""
    return bold(f"'{text}'" if quote else text)


def visible_len(s: str) -> int:
    """Calculates visible length of a string, ignoring ANSI escape codes."""
    return len(ANSI_ESCAPE.sub('', s))


def pad_visible(s: str, width: int, align_left: bool = True) -> str:
    """Pads a string considering its visible length (ignoring ANSI codes)."""
    v_len = visible_len(s)
    padding = ' ' * max(0, width - v_len)
    if align_left:
        return s + padding
    else:
        return padding + s


def truncate_visible(s: str, width: int) -> str:
    """`s` clipped to `width` visible columns, ending in an ellipsis when it lost anything.

    ANSI-aware like `pad_visible`: colour codes cost no columns, and a clipped coloured
    string still gets its reset."""
    if visible_len(s) <= width:
        return s
    if width <= 0:
        return ""
    out, used, coloured = [], 0, False
    for piece in re.split(f"({ANSI_ESCAPE.pattern})", s):
        if not piece:
            continue
        if ANSI_ESCAPE.fullmatch(piece):
            out.append(piece)
            coloured = True
            continue
        room = width - 1 - used
        out.append(piece[:room])
        used += min(room, len(piece))
        # Stop at the budget rather than carrying on through the escapes that follow:
        # a reset appended here would leave the ellipsis outside the colour it ends.
        if used >= width - 1:
            break
    return "".join(out) + "…" + (RESET if coloured else "")


def is_narrow_client() -> bool:
    """True when the CLI is driven by a narrow front-end (e.g. the Telegram bot)
    that asked for a tight wrap width via TRAINMATE_WRAP_WIDTH.

    Wide columnar tables wrap unreadably in a phone-width monospace message, so on a
    narrow client we collapse them to a vertical record layout instead. A real
    terminal (default width 80) stays False and keeps the familiar table. The 70
    threshold matches the CLI's argparse help formatter."""
    return default_wrap_width() < 70


def _column_width(headers: list, rows: list, i: int) -> int:
    """The natural width of one column: its widest cell, or its header."""
    return max(
        [visible_len(str(row[i])) for row in rows] + [visible_len(str(headers[i]))]
    )


def flex_width(
    headers: list, rows: list, flex: int, narrow: Optional[bool] = None
) -> int:
    """How wide `render_table` will let its flexible column be: its natural width, or
    whatever `display_width` has left once every other column has taken its own.

    Public because a caller that clips should be able to say so — the journal's footer
    names `-v` only when the command column actually lost something (DESIGN_logging.md
    §7.2). Never narrower than the column's own header, which still has to fit."""
    if narrow is None:
        narrow = is_narrow_client()
    if narrow:
        # One "  LABEL  value" line per column, so only the label column is spent.
        label_w = max((visible_len(h) for h in headers[1:]), default=0)
        spent = 0 if flex == 0 else 4 + label_w
    else:
        spent = sum(
            _column_width(headers, rows, i) for i in range(len(headers)) if i != flex
        ) + 3 * (len(headers) - 1)
    natural = _column_width(headers, rows, flex)
    return max(
        visible_len(str(headers[flex])), min(natural, display_width() - spent)
    )


def render_table(
    headers: list, rows: list, narrow: Optional[bool] = None, flex: Optional[int] = None
) -> str:
    """Renders a table for the active client and returns it as text.

    ``rows`` is a list of rows, each a list of pre-formatted cell strings (ANSI
    colour is fine — widths are measured with visible_len) matching ``headers``.

    On a normal-width terminal this is the familiar columnar table: a bold header,
    ``" | "`` separators, and a gray rule, with each column auto-sized to its
    widest cell. On a narrow client (the bot) the same data becomes one vertical
    record per row — the first column as a heading, the remaining columns as
    aligned ``label  value`` lines — so figures stay readable without the wide
    line being re-wrapped by the client. Records are blank-line separated.

    ``flex`` names the one column that may be clipped rather than letting the table run
    past the client's width: its cells are cut to `flex_width` and end in an ellipsis.
    Without it a single long cell wraps the whole table (DESIGN_logging.md §7.2).

    Returns the rendered text with no trailing newline."""
    if narrow is None:
        narrow = is_narrow_client()

    if flex is not None:
        room = flex_width(headers, rows, flex, narrow)
        rows = [
            [truncate_visible(str(cell), room) if i == flex else cell
             for i, cell in enumerate(row)]
            for row in rows
        ]

    if narrow:
        label_w = max((visible_len(h) for h in headers[1:]), default=0)
        cards = []
        for row in rows:
            lines = [str(row[0])]
            for header, cell in zip(headers[1:], row[1:]):
                lines.append(f"  {pad_visible(header, label_w)}  {cell}")
            cards.append("\n".join(lines))
        return "\n\n".join(cards)

    widths = [_column_width(headers, rows, i) for i in range(len(headers))]

    out = [bold(" | ".join(pad_visible(h, widths[i]) for i, h in enumerate(headers)))]
    total = sum(widths) + 3 * (len(widths) - 1)
    out.append(gray("-" * total))
    for row in rows:
        out.append(
            " | ".join(pad_visible(str(c), widths[i]) for i, c in enumerate(row))
        )
    return "\n".join(out)


# A command the text tells the athlete to run: `cmd()` single-quotes it, so a quoted
# run with a space inside is one, and its spaces must survive the wrap — a command
# split over two lines cannot be copied (DESIGN_output_verbosity.md §3.6). Quote
# boundaries keep apostrophes out: in "the athlete's plan" the `'` follows a letter,
# so it opens nothing. An opener has to start the line or follow a space or `(`, or a
# sentence quoting two commands would match from the first one's closing quote and
# swallow the prose between them.
_QUOTED_COMMAND = re.compile(r"(?:^|(?<=[\s(]))'[^\n]*?'(?![A-Za-z0-9])")
_KEEP = '\x00'      # stands in for a space that may not be broken on


def _keep_commands_whole(para: str) -> str:
    """Marks the spaces inside quoted commands as unbreakable."""
    return _QUOTED_COMMAND.sub(
        lambda m: m.group(0).replace(' ', _KEEP) if ' ' in m.group(0) else m.group(0),
        para,
    )


def keep_whole(text: str) -> str:
    """Marks `text` so no wrap splits it — for a bare command, which the quotes rule
    above cannot recognise (§3.6).

    Only for text that reaches the screen through `wrap_text`, which is what clears the
    marks: `notice`, `warn`, `fail` and `format_labeled_paragraph` do, a plain `print` does
    not. `cmd(…, quote=False)` inside one of those is the whole use."""
    return text.replace(' ', _KEEP)


def _wrap_paragraph(para: str, width: int, subsequent_indent: str) -> list:
    """One paragraph wrapped to `width`, measured in visible columns.

    textwrap counts ANSI escape bytes as columns, so a coloured paragraph would wrap
    ~10 columns short per colour span; a greedy word wrap on visible_len avoids that.
    Uncoloured text still goes through textwrap so existing layout is untouched.

    `break_on_hyphens=False` is what makes the two branches agree: the greedy loop
    below splits on spaces only, so without it a `--show-llm-context` in a sentence
    survives a coloured terminal and comes back as `--show-llm-` + `context` on a
    piped run or over Telegram, where colour is stripped.

    A quoted command takes the greedy branch whatever its colour, because that one
    never splits a word: the athlete has to be able to select the line and run it."""
    para = _keep_commands_whole(para)
    if _KEEP not in para and not ANSI_ESCAPE.search(para):
        return textwrap.wrap(
            para, width=width, subsequent_indent=subsequent_indent,
            break_on_hyphens=False,
        )
    # The paragraph's own indent belongs to its first word: `split(' ')` hands it back
    # as empty strings, and an empty `cur` below would swallow them.
    lead = para[:len(para) - len(para.lstrip(' '))]
    lines, cur = [], ''
    for word in para[len(lead):].split(' '):
        if not cur:
            cur = (lead if not lines else subsequent_indent) + word
        elif visible_len(cur) + 1 + visible_len(word) <= width:
            cur += ' ' + word
        else:
            lines.append(cur)
            cur = subsequent_indent + word
    if cur:
        lines.append(cur)
    return [line.replace(_KEEP, ' ') for line in lines]


def wrap_text(text: str, width: Optional[int] = None) -> str:
    """Wraps text at the specified width while preserving layout and indentation.

    When width is None it falls back to default_wrap_width() (80, or the
    TRAINMATE_WRAP_WIDTH override)."""
    if width is None:
        width = default_wrap_width()
    if not text:
        return text
    paragraphs = text.split('\n')
    wrapped_paragraphs = []
    for para in paragraphs:
        if not para.strip():
            wrapped_paragraphs.append('')
            continue
        
        # Detect leading whitespace and list prefix (e.g. "- ", "* ", "1. ")
        match = re.match(r'^(\s*(?:[-*+]\s+|\d+\.\s+)?)(.*)', para)
        if match:
            prefix, content = match.groups()
            indent = ' ' * len(prefix)
            # Wrap the paragraph, using the prefix indent for subsequent lines
            wrapped = _wrap_paragraph(para, width, indent)
            wrapped_paragraphs.extend(wrapped)
        else:
            wrapped_paragraphs.extend(_wrap_paragraph(para, width, ''))
            
    return '\n'.join(wrapped_paragraphs)


def format_labeled_text(
    label: str, text: str, width: Optional[int] = None, color_fn=None
) -> str:
    """Wraps and indents text dynamically under its label, optional coloring."""
    if width is None:
        width = default_wrap_width()
    indent_len = visible_len(label)
    wrapped_width = max(20, width - indent_len)
    wrapped_text = wrap_text(text, width=wrapped_width)
    if color_fn:
        wrapped_text = color_fn(wrapped_text)
    indented_text = wrapped_text.replace('\n', '\n' + ' ' * indent_len)
    return f"{label}{indented_text}"


def format_labeled_paragraph(
    label: str, text: str, width: Optional[int] = None, color_fn=None
) -> str:
    """Wraps text on a new line, indented 2 spaces deeper than the label."""
    if width is None:
        width = default_wrap_width()
    if not text:
        return f"{label}"
    match = re.match(r'^(\s*)', label)
    leading_spaces = match.group(1) if match else ""
    paragraph_indent = leading_spaces + "  "
    
    wrapped_width = max(20, width - len(paragraph_indent))
    wrapped_text = wrap_text(text, width=wrapped_width)
    if color_fn:
        wrapped_text = color_fn(wrapped_text)
    
    indented_text = paragraph_indent + wrapped_text.replace('\n', '\n' + paragraph_indent)
    return f"{label}\n{indented_text}"


def capitalized(text: str) -> str:
    """`text` with its first character upper-cased and the rest left alone.

    Not `str.capitalize()`, which lower-cases the tail: an exercise called "RDL" or a
    sport called "MTB" must survive being put at the head of a sentence."""
    return text[:1].upper() + text[1:]
