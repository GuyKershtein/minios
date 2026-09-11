"""Commands that support shell scripting: test / [, true, false, read,
source / . , seq."""

from __future__ import annotations

from ...filesystem import FSError
from ...filesystem import permissions as perm
from .base import Command


class TestCmd(Command):
    name = "test"
    aliases = ("[",)
    synopsis = "test EXPR   |   [ EXPR ]"
    help_text = ("Evaluate a conditional expression; exit 0 if true.\n"
                 "  strings: -z -n = != ;  ints: -eq -ne -lt -le -gt -ge\n"
                 "  files:   -e -f -d -r -w -x ;  negate with !")

    def run(self, ctx):
        args = ctx.argv[1:]
        if ctx.argv[0] == "[":
            if not args or args[-1] != "]":
                ctx.errorln("[: missing `]'")
                return 2
            args = args[:-1]
        return 0 if self._eval(ctx, args) else 1

    def _eval(self, ctx, a):
        if len(a) == 0:
            return False
        if len(a) == 1:
            return a[0] != ""
        if a[0] == "!":
            return not self._eval(ctx, a[1:])
        if len(a) == 2:
            op, val = a
            if op == "-z":
                return val == ""
            if op == "-n":
                return val != ""
            if op in ("-e", "-f", "-d", "-r", "-w", "-x"):
                return self._file_test(ctx, op, val)
            return False
        if len(a) == 3:
            left, op, right = a
            if op in ("=", "=="):
                return left == right
            if op == "!=":
                return left != right
            ints = ("-eq", "-ne", "-lt", "-le", "-gt", "-ge")
            if op in ints:
                try:
                    li, ri = int(left), int(right)
                except ValueError:
                    return False
                return {
                    "-eq": li == ri, "-ne": li != ri, "-lt": li < ri,
                    "-le": li <= ri, "-gt": li > ri, "-ge": li >= ri,
                }[op]
        return False

    def _file_test(self, ctx, op, path):
        try:
            node = ctx.kernel.sys_stat(path, follow=True)
        except FSError:
            return False
        if op == "-e":
            return True
        if op == "-f":
            return node.is_file
        if op == "-d":
            return node.is_dir
        need = {"-r": perm.R, "-w": perm.W, "-x": perm.X}[op]
        return perm.can(node, need, ctx.session.uid, ctx.session.gids)


class TrueCmd(Command):
    name = "true"
    synopsis = "true"
    help_text = "Do nothing, successfully (exit 0)."

    def run(self, ctx):
        return 0


class FalseCmd(Command):
    name = "false"
    synopsis = "false"
    help_text = "Do nothing, unsuccessfully (exit 1)."

    def run(self, ctx):
        return 1


class Read(Command):
    name = "read"
    synopsis = "read [var...]"
    help_text = "Read a line and split it into variables (default REPLY)."

    def run(self, ctx):
        line = None
        if ctx.stdin:
            line = ctx.stdin.splitlines()[0] if ctx.stdin.splitlines() else ""
        elif ctx.kernel.line_prompt:
            try:
                line = ctx.kernel.line_prompt("")
            except EOFError:
                return 1
        if line is None:
            return 1
        varnames = ctx.argv[1:] or ["REPLY"]
        words = line.split()
        for i, var in enumerate(varnames):
            if i == len(varnames) - 1:
                ctx.session.env[var] = " ".join(words[i:])
            else:
                ctx.session.env[var] = words[i] if i < len(words) else ""
        return 0


class Source(Command):
    name = "source"
    aliases = (".",)
    synopsis = "source FILE"
    help_text = "Execute a script in the current shell (vars/functions persist)."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("source: filename argument required")
            return 1
        try:
            content = ctx.kernel.sys_open_read(ctx.argv[1])
        except FSError as e:
            ctx.errorln(f"source: {e}")
            return 1
        from ..scripting import ScriptInterpreter
        si = ScriptInterpreter(ctx.shell)
        out, code = si.run(content, argv=[ctx.argv[1]] + ctx.argv[2:])
        ctx.write(out)
        return code


class Seq(Command):
    name = "seq"
    synopsis = "seq [first] last"
    help_text = "Print a sequence of numbers."

    def run(self, ctx):
        nums = ctx.argv[1:]
        try:
            if len(nums) == 1:
                start, end = 1, int(nums[0])
            elif len(nums) >= 2:
                start, end = int(nums[0]), int(nums[1])
            else:
                ctx.errorln("seq: missing operand")
                return 1
        except ValueError:
            ctx.errorln("seq: invalid number")
            return 1
        step = 1 if end >= start else -1
        for n in range(start, end + step, step):
            ctx.writeln(str(n))
        return 0
