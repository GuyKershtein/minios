"""A minimal terminal text editor (nano / edit).

It is line-oriented rather than full-screen, but it really opens, edits and
saves files in the virtual filesystem. Commands are entered on their own line:

    :w        write (save)          :p       print buffer with line numbers
    :q        quit (no save)        :d N     delete line N
    :wq       write and quit        :c       clear the buffer
    anything else                   appended as a new line

When input is not interactive (no terminal), it reads lines from stdin until
EOF and saves them (like ``cat > file``).
"""

from __future__ import annotations

from ...filesystem import FSError
from .base import Command


class Nano(Command):
    name = "nano"
    aliases = ("edit", "vi")
    synopsis = "nano FILE"
    help_text = ("A simple line editor.\n"
                 "  :w write   :q quit   :wq save+quit   :p print\n"
                 "  :d N delete line N   :c clear   (other input is appended)")

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("nano: missing filename")
            return 1
        path = ctx.argv[1]
        buffer = []
        try:
            existing = ctx.kernel.sys_open_read(path)
            buffer = existing.splitlines()
        except FSError:
            buffer = []

        prompt = ctx.kernel.line_prompt
        if prompt is None:
            # non-interactive: append piped stdin and save
            if ctx.stdin:
                buffer.extend(ctx.stdin.splitlines())
            return self._save(ctx, path, buffer)

        ctx.writeln(f"GNU nano — editing {path} "
                    f"({len(buffer)} lines). :wq to save, :q to quit.")
        self._print(ctx, buffer)
        while True:
            try:
                line = prompt("")
            except EOFError:
                return self._save(ctx, path, buffer)
            cmd = line.strip()
            if cmd == ":q":
                return 0
            if cmd == ":w":
                self._save(ctx, path, buffer)
                ctx.writeln(f"[ Wrote {len(buffer)} lines ]")
                continue
            if cmd == ":wq":
                return self._save(ctx, path, buffer)
            if cmd == ":p":
                self._print(ctx, buffer)
                continue
            if cmd == ":c":
                buffer = []
                continue
            if cmd.startswith(":d "):
                try:
                    n = int(cmd[3:])
                    if 1 <= n <= len(buffer):
                        del buffer[n - 1]
                except ValueError:
                    ctx.writeln("nano: :d needs a line number")
                continue
            buffer.append(line)

    def _print(self, ctx, buffer):
        for i, line in enumerate(buffer, 1):
            ctx.writeln(f"{i:>4}  {line}")

    def _save(self, ctx, path, buffer):
        data = "\n".join(buffer)
        if data:
            data += "\n"
        try:
            ctx.kernel.sys_write(path, data, append=False)
        except FSError as e:
            ctx.errorln(f"nano: {e}")
            return 1
        return 0
