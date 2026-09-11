"""Base classes for commands and the execution context passed to them."""

from __future__ import annotations

import io


class ExecutionContext:
    """Everything a command needs to run.

    A command reads from ``self.stdin`` (a string), writes output with
    ``self.write`` / ``self.error``, and returns an integer exit code. The
    shell wires the buffers together for pipes and redirection.
    """

    def __init__(self, kernel, shell, argv, stdin=""):
        self.kernel = kernel
        self.shell = shell
        self.session = kernel.session
        self.argv = argv
        self.stdin = stdin
        self._out = io.StringIO()
        self._err = io.StringIO()

    @property
    def fs(self):
        return self.kernel.fs

    def write(self, text=""):
        self._out.write(text)

    def writeln(self, text=""):
        self._out.write(text + "\n")

    def error(self, text=""):
        self._err.write(text)

    def errorln(self, text=""):
        self._err.write(text + "\n")

    @property
    def out(self):
        return self._out.getvalue()

    @property
    def err(self):
        return self._err.getvalue()


class Command:
    """Base class for all commands.

    Subclasses set ``name`` (and optionally ``aliases``, ``synopsis``,
    ``help_text``) and implement :meth:`run`.
    """

    name = "?"
    aliases = ()
    synopsis = ""
    help_text = ""

    def run(self, ctx: ExecutionContext) -> int:  # pragma: no cover - abstract
        ctx.errorln(f"{self.name}: not implemented")
        return 1

    def require_root(self, ctx):
        """Return True if the caller is root; otherwise emit an error."""
        if ctx.session.is_root:
            return True
        ctx.errorln(f"{self.name}: Permission denied (root privileges required)")
        return False

    # -- shared argument helpers -----------------------------------------
    @staticmethod
    def parse_flags(args, valued=()):
        """Split argv[1:] into (flags:set, values:dict, operands:list).

        ``valued`` names single-letter flags that consume the next token
        (e.g. -n 5). Supports combined short flags like -la and '--'.
        """
        flags = set()
        values = {}
        operands = []
        i = 0
        end_of_flags = False
        while i < len(args):
            a = args[i]
            if not end_of_flags and a == "--":
                end_of_flags = True
            elif not end_of_flags and a.startswith("--") and len(a) > 2:
                flags.add(a)
            elif not end_of_flags and a.startswith("-") and len(a) > 1:
                j = 1
                while j < len(a):
                    ch = a[j]
                    if ch in valued:
                        rest = a[j + 1:]
                        if rest:
                            values[ch] = rest
                        else:
                            i += 1
                            values[ch] = args[i] if i < len(args) else ""
                        break
                    flags.add(ch)
                    j += 1
            else:
                operands.append(a)
            i += 1
        return flags, values, operands
