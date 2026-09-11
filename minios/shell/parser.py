"""Command-line parser for minish.

Turns a raw line into a list of *chains*. Each chain is::

    (connector, Pipeline)

where ``connector`` is None for the first chain and one of ``&&``, ``||``,
``;`` otherwise. A ``Pipeline`` is a list of ``Command`` objects joined by
pipes. Each ``Command`` carries its argv plus any redirections.

Supported syntax:
    quoting          'single' and "double"
    expansion        $VAR  ${VAR}  $?  ~
    pipes            cmd1 | cmd2
    redirection      > >> <
    chaining         &&  ||  ;
"""

from __future__ import annotations


class ParseError(Exception):
    pass


class Command:
    def __init__(self):
        self.argv = []
        self.stdin_file = None       # path for '<'
        self.stdout_file = None      # path for '>' / '>>'
        self.append = False

    def __repr__(self):
        return f"Command(argv={self.argv!r})"


class Pipeline:
    def __init__(self):
        self.commands = []
        self.background = False

    def __repr__(self):
        return f"Pipeline({self.commands!r})"


_OPERATORS = ("&&", "||", ">>", "|", "<", ">", ";", "&")


def tokenize(line, env, last_status=0):
    """Split ``line`` into tokens.

    Returns a list of ``(kind, value)`` where kind is 'word' or 'op'. Variable
    and tilde expansion happen here so quoting is respected correctly.
    """
    tokens = []
    i = 0
    n = len(line)
    cur = ""            # current word buffer
    have_word = False   # whether we're mid-word (even if empty via "")

    def flush():
        nonlocal cur, have_word
        if have_word:
            tokens.append(("word", cur))
        cur = ""
        have_word = False

    def expand(text):
        return _expand_vars(text, env, last_status)

    while i < n:
        c = line[i]

        # operators (only outside quotes — handled here since we're not in one)
        matched_op = None
        for op in _OPERATORS:
            if line.startswith(op, i):
                matched_op = op
                break
        if matched_op:
            flush()
            tokens.append(("op", matched_op))
            i += len(matched_op)
            continue

        if c.isspace():
            flush()
            i += 1
            continue

        if c == "'":
            # literal until next single quote
            j = line.find("'", i + 1)
            if j == -1:
                raise ParseError("unterminated single quote")
            cur += line[i + 1:j]
            have_word = True
            i = j + 1
            continue

        if c == '"':
            j = i + 1
            buf = ""
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n and line[j + 1] in '"\\$':
                    buf += line[j + 1]
                    j += 2
                    continue
                buf += line[j]
                j += 1
            if j >= n:
                raise ParseError("unterminated double quote")
            cur += expand(buf)
            have_word = True
            i = j + 1
            continue

        if c == "\\" and i + 1 < n:
            cur += line[i + 1]
            have_word = True
            i += 2
            continue

        if c == "~" and not have_word and (
            i + 1 >= n or line[i + 1] in ("/",) or line[i + 1].isspace()
        ):
            cur += env.get("HOME", "/root")
            have_word = True
            i += 1
            continue

        # accumulate a bare character, expanding $ sequences lazily
        if c == "$":
            var, consumed = _read_var(line, i, env, last_status)
            cur += var
            have_word = True
            i += consumed
            continue

        cur += c
        have_word = True
        i += 1

    flush()
    return tokens


def _read_var(line, i, env, last_status):
    """Read a $VAR / ${VAR} / $? starting at index i (line[i] == '$')."""
    n = len(line)
    j = i + 1
    if j < n and line[j] == "?":
        return str(last_status), 2
    if j < n and line[j] in "@#*":
        return env.get(line[j], ""), 2
    if j < n and line[j] == "{":
        k = line.find("}", j + 1)
        if k == -1:
            return "$", 1
        name = line[j + 1:k]
        return env.get(name, ""), (k - i + 1)
    name = ""
    while j < n and (line[j].isalnum() or line[j] == "_"):
        name += line[j]
        j += 1
    if not name:
        return "$", 1
    return env.get(name, ""), (j - i)


def _expand_vars(text, env, last_status):
    out = ""
    i = 0
    while i < len(text):
        if text[i] == "$":
            val, consumed = _read_var(text, i, env, last_status)
            out += val
            i += consumed
        else:
            out += text[i]
            i += 1
    return out


def parse(line, env, last_status=0):
    """Parse a full line into ``[(connector, Pipeline), ...]``."""
    tokens = tokenize(line, env, last_status)
    chains = []
    connector = None
    pipeline = Pipeline()
    command = Command()

    def end_command():
        if command.argv or command.stdin_file or command.stdout_file:
            pipeline.commands.append(command)

    def end_pipeline(next_connector):
        nonlocal pipeline, command, connector
        end_command()
        if pipeline.commands:
            chains.append((connector, pipeline))
        pipeline = Pipeline()
        command = Command()
        connector = next_connector

    idx = 0
    expect_redirect = None
    while idx < len(tokens):
        kind, val = tokens[idx]
        if expect_redirect:
            if kind != "word":
                raise ParseError("expected filename after redirection")
            if expect_redirect == "<":
                command.stdin_file = val
            else:
                command.stdout_file = val
                command.append = (expect_redirect == ">>")
            expect_redirect = None
            idx += 1
            continue

        if kind == "word":
            command.argv.append(val)
        elif val == "|":
            end_command()
            command = Command()
        elif val in (">", ">>", "<"):
            expect_redirect = val
        elif val == ";":
            end_pipeline(";")
        elif val == "&&":
            end_pipeline("&&")
        elif val == "||":
            end_pipeline("||")
        elif val == "&":
            pipeline.background = True
        idx += 1

    if expect_redirect:
        raise ParseError("expected filename after redirection")
    end_command()
    if pipeline.commands:
        chains.append((connector, pipeline))
    return chains
