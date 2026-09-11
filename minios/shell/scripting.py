"""A small block-structured interpreter for minish scripts.

Supports a useful subset of shell scripting:
    variables and $VAR / $1 / $@ / $# expansion (via the shared parser)
    if / elif / else / fi
    for VAR in LIST; do ... done
    while COND; do ... done
    functions:  name() { ... }
    exit / return / break / continue

Simple commands, pipes and redirection are delegated back to the shell, so
everything the interactive shell can do is available inside scripts too.
"""

from __future__ import annotations

import re

from . import parser as _parser

_INLINE_FUNC = re.compile(r"^([A-Za-z_]\w*)\s*\(\s*\)\s*\{(.*)\}\s*$")


class ExitScript(Exception):
    def __init__(self, code=0):
        self.code = code


class ReturnFunc(Exception):
    def __init__(self, code=0):
        self.code = code


class BreakLoop(Exception):
    pass


class ContinueLoop(Exception):
    pass


class _Cursor:
    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    @property
    def eof(self):
        return self.i >= len(self.lines)

    def peek(self):
        return self.lines[self.i]

    def next(self):
        ln = self.lines[self.i]
        self.i += 1
        return ln


def _first(line):
    return line.split()[0] if line.split() else ""


class ScriptInterpreter:
    MAX_LOOP = 100000

    def __init__(self, shell):
        self.shell = shell
        self.out = []
        self.last = 0

    @property
    def env(self):
        return self.shell.session.env

    # -- entry ------------------------------------------------------------
    def run(self, text, argv=None):
        """Run a script body. Returns (output, exit_code)."""
        self.out = []
        saved = self._set_positionals(argv or ["minish"])
        lines = self._logical_lines(text)
        code = 0
        try:
            self._exec_lines(_Cursor(lines), execute=True)
        except ExitScript as e:
            code = e.code
        except ReturnFunc as e:
            code = e.code
        finally:
            self._restore_positionals(saved)
        return "".join(self.out), code if code is not None else self.last

    # -- positional params ------------------------------------------------
    def _set_positionals(self, argv):
        keys = [str(i) for i in range(len(argv))] + ["#", "@", "*"]
        saved = {k: self.env.get(k) for k in keys}
        for i, a in enumerate(argv):
            self.env[str(i)] = a
        self.env["#"] = str(len(argv) - 1)
        self.env["@"] = " ".join(argv[1:])
        self.env["*"] = " ".join(argv[1:])
        return saved

    def _restore_positionals(self, saved):
        for k, v in saved.items():
            if v is None:
                self.env.pop(k, None)
            else:
                self.env[k] = v

    # -- lexing -----------------------------------------------------------
    def _logical_lines(self, text):
        result = []
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            # expand a one-line function definition into a multi-line block
            m = _INLINE_FUNC.match(s)
            if m:
                name, body = m.group(1), m.group(2)
                result.append(f"{name}() {{")
                for stmt in self._split_semicolons(body):
                    stmt = stmt.strip()
                    if stmt:
                        result.append(stmt)
                result.append("}")
                continue
            for part in self._split_semicolons(s):
                part = part.strip()
                if part:
                    result.append(part)
        return result

    @staticmethod
    def _split_semicolons(s):
        parts, buf, quote = [], "", None
        i = 0
        while i < len(s):
            c = s[i]
            if quote:
                buf += c
                if c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
                buf += c
            elif c == ";":
                parts.append(buf)
                buf = ""
            else:
                buf += c
            i += 1
        if buf:
            parts.append(buf)
        return parts

    # -- execution --------------------------------------------------------
    def _exec_lines(self, cur, execute):
        while not cur.eof:
            line = cur.peek()
            w = _first(line)
            if w == "if":
                self._do_if(cur, execute)
            elif w == "for":
                self._do_for(cur, execute)
            elif w == "while":
                self._do_while(cur, execute)
            elif w == "function" or self._is_func_def(line):
                self._do_func(cur)
            elif w in ("fi", "done", "else", "elif", "then", "do", "}"):
                # a stray terminator: stop so the caller can handle it
                return w
            elif w == "exit":
                cur.next()
                if not execute:
                    continue
                raise ExitScript(self._code_arg(line))
            elif w == "return":
                cur.next()
                if not execute:
                    continue
                raise ReturnFunc(self._code_arg(line))
            elif w == "break":
                cur.next()
                if execute:
                    raise BreakLoop()
            elif w == "continue":
                cur.next()
                if execute:
                    raise ContinueLoop()
            else:
                cur.next()
                if execute:
                    self._run_line(line)
        return None

    def _code_arg(self, line):
        toks = line.split()
        if len(toks) > 1 and toks[1].lstrip("-").isdigit():
            return int(toks[1])
        return self.last

    def _run_line(self, line):
        out, code = self.shell.execute_line(line, record_history=False)
        self.out.append(out)
        self.last = code
        return code

    def _truth(self, cond):
        cond = cond.strip()
        if not cond:
            return False
        out, code = self.shell.execute_line(cond, record_history=False)
        self.out.append(out)
        self.last = code
        return code == 0

    def _expand_words(self, text):
        text = self.shell._expand_command_subst(text)
        try:
            toks = _parser.tokenize(text, self.env, self.last)
            return [v for k, v in toks if k == "word"]
        except _parser.ParseError:
            return text.split()

    # -- block collectors -------------------------------------------------
    def _collect(self, cur, terminators):
        """Collect lines until a top-level terminator; consume & return it."""
        body, depth = [], 0
        while not cur.eof:
            line = cur.peek()
            w = _first(line)
            if depth == 0 and w in terminators:
                cur.next()
                return body, line
            if w in ("if", "for", "while", "case"):
                depth += 1
            elif self._is_func_def(line) or line.endswith("{"):
                depth += 1
            if w in ("fi", "done", "esac") or w == "}":
                depth -= 1
            body.append(cur.next())
        return body, None

    def _skip_to(self, cur, kw):
        """Consume lines up to and including a line beginning with kw."""
        while not cur.eof:
            if _first(cur.peek()) == kw:
                cur.next()
                return
            cur.next()

    # -- constructs -------------------------------------------------------
    def _do_if(self, cur, execute):
        line = cur.next()
        cond = line[2:].strip()
        self._skip_to(cur, "then")
        body, term = self._collect(cur, ("elif", "else", "fi"))
        taken = execute and self._truth(cond)
        if taken:
            self._exec_lines(_Cursor(body), True)
        while term is not None and _first(term) == "elif":
            econd = term.split(None, 1)[1] if len(term.split(None, 1)) > 1 else ""
            self._skip_to(cur, "then")
            body, term = self._collect(cur, ("elif", "else", "fi"))
            if execute and not taken and self._truth(econd):
                taken = True
                self._exec_lines(_Cursor(body), True)
        if term is not None and _first(term) == "else":
            body, term = self._collect(cur, ("fi",))
            if execute and not taken:
                self._exec_lines(_Cursor(body), True)

    def _do_for(self, cur, execute):
        line = cur.next()
        toks = line.split()
        var = toks[1] if len(toks) > 1 else "i"
        items = []
        if "in" in toks:
            idx = toks.index("in")
            items = self._expand_words(" ".join(toks[idx + 1:]))
        self._skip_to(cur, "do")
        body, _ = self._collect(cur, ("done",))
        if not execute:
            return
        for it in items:
            self.env[var] = it
            try:
                self._exec_lines(_Cursor(body), True)
            except ContinueLoop:
                continue
            except BreakLoop:
                break

    def _do_while(self, cur, execute):
        line = cur.next()
        cond = line[5:].strip()
        self._skip_to(cur, "do")
        body, _ = self._collect(cur, ("done",))
        if not execute:
            return
        guard = 0
        while self._truth(cond):
            guard += 1
            if guard > self.MAX_LOOP:
                self.out.append("minish: while: loop limit exceeded\n")
                break
            try:
                self._exec_lines(_Cursor(body), True)
            except ContinueLoop:
                continue
            except BreakLoop:
                break

    def _is_func_def(self, line):
        s = line.strip()
        if s.startswith("function "):
            return True
        # name() {  or  name ( )
        head = s.split("(")[0].strip()
        return "(" in s and head.isidentifier() and ")" in s

    def _do_func(self, cur):
        line = cur.next()
        s = line.strip()
        if s.startswith("function "):
            name = s[len("function "):].split("(")[0].split("{")[0].strip()
        else:
            name = s.split("(")[0].strip()
        if not s.rstrip().endswith("{"):
            self._skip_to(cur, "{")
        body, _ = self._collect(cur, ("}",))
        self.shell.functions[name] = body

    # -- function invocation (called by the shell) ------------------------
    def call_function(self, name, args):
        body = self.shell.functions[name]
        self.out = []
        saved = self._set_positionals([name] + list(args))
        code = 0
        try:
            self._exec_lines(_Cursor(list(body)), True)
        except ReturnFunc as e:
            code = e.code
        except ExitScript as e:
            code = e.code
        finally:
            self._restore_positionals(saved)
        return "".join(self.out), code
