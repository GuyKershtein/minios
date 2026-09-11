"""More common userland utilities: wc, sort, uniq, cut, tee, which, date,
basename, dirname, yes, wc."""

from __future__ import annotations

import time

from ...filesystem import FSError
from .base import Command


def _gather(ctx, operands):
    """Yield (label, text) from files, or from stdin if no files given."""
    if not operands:
        return [("", ctx.stdin)]
    out = []
    for f in operands:
        try:
            out.append((f, ctx.kernel.sys_open_read(f)))
        except FSError as e:
            ctx.errorln(f"{ctx.argv[0]}: {e}")
    return out


class Wc(Command):
    name = "wc"
    synopsis = "wc [-l] [-w] [-c] [file...]"
    help_text = "Count lines, words and bytes. -l lines, -w words, -c bytes."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        show_l = "l" in flags
        show_w = "w" in flags
        show_c = "c" in flags
        if not (show_l or show_w or show_c):
            show_l = show_w = show_c = True
        rc = 0
        tot_l = tot_w = tot_c = 0
        sources = _gather(ctx, operands)
        for label, text in sources:
            lines = text.count("\n")
            words = len(text.split())
            chars = len(text)
            tot_l += lines
            tot_w += words
            tot_c += chars
            cols = []
            if show_l:
                cols.append(f"{lines:>4}")
            if show_w:
                cols.append(f"{words:>4}")
            if show_c:
                cols.append(f"{chars:>4}")
            ctx.writeln(" ".join(cols) + (f" {label}" if label else ""))
        if len(operands) > 1:
            cols = []
            if show_l:
                cols.append(f"{tot_l:>4}")
            if show_w:
                cols.append(f"{tot_w:>4}")
            if show_c:
                cols.append(f"{tot_c:>4}")
            ctx.writeln(" ".join(cols) + " total")
        return rc


class Sort(Command):
    name = "sort"
    synopsis = "sort [-r] [-n] [-u] [file...]"
    help_text = "Sort lines. -r reverse, -n numeric, -u unique."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        text = "".join(t for _, t in _gather(ctx, operands))
        lines = text.splitlines()
        if "n" in flags:
            def key(x):
                try:
                    return (0, float(x.split()[0]) if x.split() else 0.0)
                except ValueError:
                    return (1, 0.0)
            lines.sort(key=key)
        else:
            lines.sort()
        if "r" in flags:
            lines.reverse()
        if "u" in flags:
            seen, uniq = set(), []
            for ln in lines:
                if ln not in seen:
                    seen.add(ln)
                    uniq.append(ln)
            lines = uniq
        for ln in lines:
            ctx.writeln(ln)
        return 0


class Uniq(Command):
    name = "uniq"
    synopsis = "uniq [-c] [file]"
    help_text = "Filter adjacent duplicate lines. -c prefixes counts."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        text = "".join(t for _, t in _gather(ctx, operands))
        prev = object()
        count = 0
        for ln in text.splitlines():
            if ln == prev:
                count += 1
            else:
                if prev is not object() and count:
                    self._emit(ctx, prev, count, "c" in flags)
                prev = ln
                count = 1
        if prev is not object() and count:
            self._emit(ctx, prev, count, "c" in flags)
        return 0

    def _emit(self, ctx, line, count, show_count):
        if show_count:
            ctx.writeln(f"{count:>7} {line}")
        else:
            ctx.writeln(line)


class Cut(Command):
    name = "cut"
    synopsis = "cut -d DELIM -f N [file...]"
    help_text = "Select fields from each line by delimiter."

    def run(self, ctx):
        _, values, operands = self.parse_flags(ctx.argv[1:], valued=("d", "f"))
        delim = values.get("d", "\t")
        try:
            fields = [int(x) for x in values.get("f", "1").split(",")]
        except ValueError:
            ctx.errorln("cut: invalid field list")
            return 1
        text = "".join(t for _, t in _gather(ctx, operands))
        for ln in text.splitlines():
            parts = ln.split(delim)
            picked = [parts[i - 1] for i in fields if 0 < i <= len(parts)]
            ctx.writeln(delim.join(picked))
        return 0


class Tee(Command):
    name = "tee"
    synopsis = "tee [-a] file..."
    help_text = "Copy stdin to stdout and to files. -a appends."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        data = ctx.stdin
        ctx.write(data)
        for f in operands:
            try:
                ctx.kernel.sys_write(f, data, append="a" in flags)
            except FSError as e:
                ctx.errorln(f"tee: {e}")
                return 1
        return 0


class Which(Command):
    name = "which"
    synopsis = "which name..."
    help_text = "Locate a command (builtin or an executable on PATH)."

    def run(self, ctx):
        rc = 0
        for name in ctx.argv[1:]:
            if name in ctx.shell.registry:
                ctx.writeln(f"{name}: shell built-in command")
                continue
            path = ctx.shell._resolve_executable(name)
            if path:
                ctx.writeln(path)
            else:
                rc = 1
        return rc


class Date(Command):
    name = "date"
    synopsis = "date"
    help_text = "Print the current date and time."

    def run(self, ctx):
        ctx.writeln(time.strftime("%a %b %e %H:%M:%S %Z %Y"))
        return 0


class Basename(Command):
    name = "basename"
    synopsis = "basename path [suffix]"
    help_text = "Strip directory (and optional suffix) from a path."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("basename: missing operand")
            return 1
        base = ctx.argv[1].rstrip("/").rsplit("/", 1)[-1]
        if len(ctx.argv) > 2 and base.endswith(ctx.argv[2]):
            base = base[: -len(ctx.argv[2])]
        ctx.writeln(base)
        return 0


class Dirname(Command):
    name = "dirname"
    synopsis = "dirname path"
    help_text = "Strip the last component from a path."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("dirname: missing operand")
            return 1
        p = ctx.argv[1].rstrip("/")
        ctx.writeln(p.rsplit("/", 1)[0] if "/" in p else ".")
        return 0


class Yes(Command):
    name = "yes"
    synopsis = "yes [string]"
    help_text = "Print a string repeatedly (bounded to 100 lines here)."

    def run(self, ctx):
        s = " ".join(ctx.argv[1:]) or "y"
        for _ in range(100):
            ctx.writeln(s)
        return 0
