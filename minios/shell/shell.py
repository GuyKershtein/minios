"""The shell interpreter (minish).

Takes a raw line, parses it into chains/pipelines/redirections, then executes
each command by looking it up in the registry and handing it an
:class:`ExecutionContext`. Handles pipes, I/O redirection, ``&& || ;`` chaining,
``NAME=value`` assignments and ``--help``.
"""

from __future__ import annotations

import re

from ..filesystem import FSError
from . import parser as _parser
from .commands import ExecutionContext, build_registry

_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FUNCDEF_RE = re.compile(r"^\s*[A-Za-z_]\w*\s*\(\s*\)\s*\{")


class Shell:
    def __init__(self, kernel):
        self.kernel = kernel
        self.registry = build_registry()
        self.last_status = 0
        self.request_exit = False
        self.functions = {}
        from .scripting import ScriptInterpreter
        self.interpreter = ScriptInterpreter(self)

    @property
    def session(self):
        return self.kernel.session

    # -- top level --------------------------------------------------------
    def execute_line(self, line, record_history=True):
        """Run one input line. Returns (terminal_output:str, exit_code:int)."""
        line = line.lstrip("﻿")  # tolerate a stray UTF-8 BOM on piped input
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return "", self.last_status
        if record_history:
            self.session.history.append(line.rstrip("\n"))

        # command substitution: $(...) and `...`
        line = self._expand_command_subst(line)

        # a compound statement or function definition typed on one line is
        # handed to the script interpreter (which understands if/for/while/{})
        first = stripped.split()[0] if stripped.split() else ""
        if first in ("if", "for", "while", "case", "function") or \
                _FUNCDEF_RE.match(stripped):
            from .scripting import ScriptInterpreter
            out, code = ScriptInterpreter(self).run(line)
            self.last_status = code
            self.session.env["?"] = str(code)
            return out, code

        try:
            chains = _parser.parse(line, self.session.env, self.last_status)
        except _parser.ParseError as e:
            self.last_status = 2
            return f"minish: syntax error: {e}\n", 2

        output = []
        for connector, pipeline in chains:
            if connector == "&&" and self.last_status != 0:
                continue
            if connector == "||" and self.last_status == 0:
                continue
            if pipeline.background:
                out, code = self._spawn_background(pipeline)
            else:
                out, code = self._run_pipeline(pipeline)
            output.append(out)
            self.last_status = code
            self.session.env["?"] = str(code)
            # advance simulated CPU time so processes accrue time / jobs finish
            if getattr(self.kernel, "procmgr", None):
                self.kernel.procmgr.scheduler.tick(1)
        return "".join(output), self.last_status

    def _expand_command_subst(self, line, depth=0):
        """Expand $(...) and `...` by running the inner command and inserting
        its stdout (trailing newlines stripped)."""
        if depth > 10 or ("$(" not in line and "`" not in line):
            return line
        out = []
        i = 0
        n = len(line)
        quote = None
        while i < n:
            c = line[i]
            if quote == "'":
                out.append(c)
                if c == "'":
                    quote = None
                i += 1
                continue
            if c in "'\"" and quote is None:
                quote = c
                out.append(c)
                i += 1
                continue
            if c == quote == '"':
                quote = None
                out.append(c)
                i += 1
                continue
            if line[i] == "$" and i + 1 < n and line[i + 1] == "(":
                depth_p = 1
                j = i + 2
                while j < n and depth_p:
                    if line[j] == "(":
                        depth_p += 1
                    elif line[j] == ")":
                        depth_p -= 1
                    if depth_p:
                        j += 1
                inner = line[i + 2:j]
                out.append(self._run_capture(inner))
                i = j + 1
            elif line[i] == "`":
                j = line.find("`", i + 1)
                if j == -1:
                    out.append(line[i:])
                    break
                inner = line[i + 1:j]
                out.append(self._run_capture(inner))
                i = j + 1
            else:
                out.append(line[i])
                i += 1
        return "".join(out)

    def _run_capture(self, inner):
        text, _ = self.execute_line(inner, record_history=False)
        return text.strip("\n").replace("\n", " ")

    def _spawn_background(self, pipeline):
        """Launch a pipeline as a background job (``cmd &``)."""
        cmd = pipeline.commands[-1]
        if not cmd.argv:
            return "", 0
        name = cmd.argv[0]
        remaining = None
        if name == "sleep" and len(cmd.argv) > 1:
            try:
                remaining = int(float(cmd.argv[1]))
            except ValueError:
                remaining = None
        proc = self.kernel.procmgr.spawn(name, list(cmd.argv), state="R",
                                         remaining=remaining, background=True)
        return f"[{proc.job_id}] {proc.pid}\n", 0

    # -- pipeline ---------------------------------------------------------
    def _run_pipeline(self, pipeline):
        terminal_out = []
        prev_stdout = ""
        code = 0
        n = len(pipeline.commands)
        for i, cmd in enumerate(pipeline.commands):
            is_last = i == n - 1
            # stdin: from redirect file, else from previous pipe stage
            if cmd.stdin_file is not None:
                try:
                    stdin = self.kernel.sys_open_read(cmd.stdin_file)
                except FSError as e:
                    terminal_out.append(f"minish: {cmd.stdin_file}: {e}\n")
                    code = 1
                    break
            else:
                stdin = prev_stdout if i > 0 else ""

            out, err, code = self._run_command(cmd.argv, stdin)

            if err:
                terminal_out.append(err)

            if cmd.stdout_file is not None:
                try:
                    self.kernel.sys_write(cmd.stdout_file, out,
                                          append=cmd.append)
                except FSError as e:
                    terminal_out.append(f"minish: {cmd.stdout_file}: {e}\n")
                    code = 1
                prev_stdout = ""
            elif is_last:
                terminal_out.append(out)
            else:
                prev_stdout = out
        return "".join(terminal_out), code

    # -- single command ---------------------------------------------------
    def _run_command(self, argv, stdin):
        if not argv:
            return "", "", 0

        # leading NAME=value assignments
        assigns = []
        while argv and _ASSIGN_RE.match(argv[0]):
            assigns.append(argv[0])
            argv = argv[1:]
        if assigns and not argv:
            for a in assigns:
                k, _, v = a.partition("=")
                self.session.env[k] = v
            return "", "", 0
        saved_env = None
        if assigns:
            saved_env = dict(self.session.env)
            for a in assigns:
                k, _, v = a.partition("=")
                self.session.env[k] = v

        try:
            name = argv[0]
            cmd = self.registry.get(name)
            if cmd is None:
                # shell function?
                if name in self.functions:
                    from .scripting import ScriptInterpreter
                    out, code = ScriptInterpreter(self).call_function(
                        name, argv[1:])
                    return out, "", code
                # executable file on disk (script or installed binary)?
                path = self._resolve_executable(name)
                if path is not None:
                    return self._exec_file(path, argv, stdin)
                return "", f"minish: {name}: command not found\n", 127

            if "--help" in argv[1:]:
                return (f"{cmd.name} — {cmd.synopsis}\n{cmd.help_text}\n",
                        "", 0)

            ctx = ExecutionContext(self.kernel, self, argv, stdin=stdin)
            try:
                code = cmd.run(ctx)
            except FSError as e:
                return ctx.out, ctx.err + f"{name}: {e}\n", 1
            except Exception as e:  # keep the shell alive on command bugs
                return ctx.out, ctx.err + f"{name}: internal error: {e}\n", 1
            return ctx.out, ctx.err, int(code or 0)
        finally:
            if saved_env is not None:
                self.session.env = saved_env

    # -- executable resolution (scripts / installed binaries) -------------
    def _resolve_executable(self, name):
        from ..filesystem import FSError
        from ..filesystem.permissions import can, X
        cred = self.session
        candidates = []
        if "/" in name:
            candidates.append(name)
        else:
            for d in self.session.env.get("PATH", "").split(":"):
                if d:
                    candidates.append(d.rstrip("/") + "/" + name)
        for cand in candidates:
            try:
                node = self.kernel.fs.resolve(cand, self.session.cwd, cred)
            except FSError:
                continue
            if node.is_file:
                # explicit paths are returned even if not executable (so we can
                # report "Permission denied"); PATH hits must be executable
                if "/" in name or can(node, X, cred.uid, cred.gids):
                    return self.kernel.fs.path_of(node)
        return None

    def _exec_file(self, path, argv, stdin):
        from ..filesystem.permissions import can, X
        node = self.kernel.fs.resolve(path, self.session.cwd, self.session)
        if not can(node, X, self.session.uid, self.session.gids):
            return "", f"minish: {argv[0]}: Permission denied\n", 126
        content = self.kernel.sys_open_read(path)
        from .scripting import ScriptInterpreter
        si = ScriptInterpreter(self)
        out, code = si.run(content, argv=[argv[0]] + list(argv[1:]))
        return out, "", code
