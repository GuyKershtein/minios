"""Core userland commands.

Every command here works through the kernel's syscall layer and the shell's
state — none of them fabricate output. ``ls`` asks the filesystem for real
directory entries; ``cat`` reads real inode content; ``cd`` mutates the real
session cwd, and so on.
"""

from __future__ import annotations

import fnmatch
import time

from ...filesystem import FSError
from ...filesystem import permissions as perm
from .base import Command


def _uname(ctx, uid):
    return ctx.kernel.userdb.uname(uid)


def _gname(ctx, gid):
    return ctx.kernel.userdb.gname(gid)


class Pwd(Command):
    name = "pwd"
    synopsis = "pwd"
    help_text = "Print the absolute path of the current working directory."

    def run(self, ctx):
        ctx.writeln(ctx.session.cwd)
        return 0


class Cd(Command):
    name = "cd"
    synopsis = "cd [dir]"
    help_text = "Change the current directory. With no argument, go to $HOME."

    def run(self, ctx):
        target = ctx.argv[1] if len(ctx.argv) > 1 else ctx.session.home
        if target == "-":
            target = ctx.session.env.get("OLDPWD", ctx.session.cwd)
        old = ctx.session.cwd
        try:
            ctx.kernel.sys_chdir(target)
            ctx.session.env["OLDPWD"] = old
            return 0
        except FSError as e:
            ctx.errorln(f"cd: {e}")
            return 1


class Ls(Command):
    name = "ls"
    synopsis = "ls [-l] [-a] [-h] [path...]"
    help_text = ("List directory contents.\n"
                 "  -l  long format\n  -a  show hidden entries\n"
                 "  -h  human-readable sizes (with -l)")

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        long = "l" in flags
        show_all = "a" in flags
        human = "h" in flags
        paths = operands or ["."]
        rc = 0
        multiple = len(paths) > 1
        blocks = []
        for p in paths:
            try:
                node = ctx.kernel.sys_stat(p)
            except FSError as e:
                ctx.errorln(f"ls: {e}")
                rc = 1
                continue
            header = f"{p}:" if multiple else None
            if node.is_dir:
                entries = ctx.kernel.sys_readdir(p)
                lines = self._format_dir(ctx, entries, long, show_all, human)
            else:
                lines = self._format_entries(ctx, [(node.name, node)], long, human)
            block = []
            if header:
                block.append(header)
            block.extend(lines)
            blocks.append("\n".join(block))
        ctx.write("\n\n".join(b for b in blocks if b))
        if blocks and any(blocks):
            ctx.write("\n")
        return rc

    def _format_dir(self, ctx, entries, long, show_all, human):
        entries = [(n, nd) for n, nd in entries
                   if show_all or not n.startswith(".")]
        return self._format_entries(ctx, entries, long, human)

    def _format_entries(self, ctx, entries, long, human):
        if not long:
            return [n for n, _ in entries] if entries else []
        rows = []
        for name, nd in entries:
            perms = perm.mode_to_string(nd.mode, nd.ftype)
            size = _human(nd.size) if human else str(nd.size)
            t = time.strftime("%b %e %H:%M", time.localtime(nd.mtime))
            suffix = f" -> {nd.target}" if nd.is_link else ""
            rows.append(f"{perms} {nd.nlink:>2} {_uname(ctx, nd.uid):<6} "
                        f"{_gname(ctx, nd.gid):<6} {size:>7} {t} {name}{suffix}")
        return rows


def _human(n):
    for unit in ("", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n}{unit}" if unit == "" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


class Mkdir(Command):
    name = "mkdir"
    synopsis = "mkdir [-p] dir..."
    help_text = "Create directories. -p makes parent directories as needed."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        if not operands:
            ctx.errorln("mkdir: missing operand")
            return 1
        rc = 0
        for d in operands:
            try:
                ctx.kernel.sys_mkdir(d, parents="p" in flags)
            except FSError as e:
                ctx.errorln(f"mkdir: {e}")
                rc = 1
        return rc


class Rmdir(Command):
    name = "rmdir"
    synopsis = "rmdir dir..."
    help_text = "Remove empty directories."

    def run(self, ctx):
        rc = 0
        for d in ctx.argv[1:]:
            try:
                ctx.kernel.sys_rmdir(d)
            except FSError as e:
                ctx.errorln(f"rmdir: {e}")
                rc = 1
        return rc


class Touch(Command):
    name = "touch"
    synopsis = "touch file..."
    help_text = "Create empty files or update their modification time."

    def run(self, ctx):
        _, _, operands = self.parse_flags(ctx.argv[1:])
        if not operands:
            ctx.errorln("touch: missing file operand")
            return 1
        rc = 0
        for f in operands:
            try:
                ctx.kernel.sys_create(f)
            except FSError as e:
                ctx.errorln(f"touch: {e}")
                rc = 1
        return rc


class Cat(Command):
    name = "cat"
    synopsis = "cat [file...]"
    help_text = "Concatenate files to output. With no file, echo stdin."

    def run(self, ctx):
        _, _, operands = self.parse_flags(ctx.argv[1:])
        if not operands:
            ctx.write(ctx.stdin)
            return 0
        rc = 0
        for f in operands:
            if f == "-":
                ctx.write(ctx.stdin)
                continue
            try:
                ctx.write(ctx.kernel.sys_open_read(f))
            except FSError as e:
                ctx.errorln(f"cat: {e}")
                rc = 1
        return rc


class Echo(Command):
    name = "echo"
    synopsis = "echo [-n] [-e] [text...]"
    help_text = "Print text. -n omits the trailing newline."

    def run(self, ctx):
        args = ctx.argv[1:]
        newline = True
        interpret = False
        while args and args[0] in ("-n", "-e", "-ne", "-en"):
            if "n" in args[0]:
                newline = False
            if "e" in args[0]:
                interpret = True
            args = args[1:]
        text = " ".join(args)
        if interpret:
            text = text.replace("\\n", "\n").replace("\\t", "\t")
        ctx.write(text + ("\n" if newline else ""))
        return 0


class Rm(Command):
    name = "rm"
    synopsis = "rm [-r] [-f] file..."
    help_text = "Remove files or directories. -r recursive, -f ignore missing."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        recursive = "r" in flags or "R" in flags
        force = "f" in flags
        rc = 0
        for f in operands:
            try:
                ctx.kernel.sys_unlink(f, recursive=recursive)
            except FSError as e:
                if not force:
                    ctx.errorln(f"rm: {e}")
                    rc = 1
        return rc


class Cp(Command):
    name = "cp"
    synopsis = "cp [-r] src... dest"
    help_text = "Copy files or directories. -r copies directories recursively."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        if len(operands) < 2:
            ctx.errorln("cp: missing destination")
            return 1
        *srcs, dest = operands
        recursive = "r" in flags or "R" in flags
        rc = 0
        for s in srcs:
            try:
                ctx.kernel.sys_copy(s, dest, recursive=recursive)
            except FSError as e:
                ctx.errorln(f"cp: {e}")
                rc = 1
        return rc


class Mv(Command):
    name = "mv"
    synopsis = "mv src... dest"
    help_text = "Move or rename files and directories."

    def run(self, ctx):
        _, _, operands = self.parse_flags(ctx.argv[1:])
        if len(operands) < 2:
            ctx.errorln("mv: missing destination")
            return 1
        *srcs, dest = operands
        rc = 0
        for s in srcs:
            try:
                ctx.kernel.sys_rename(s, dest)
            except FSError as e:
                ctx.errorln(f"mv: {e}")
                rc = 1
        return rc


class Ln(Command):
    name = "ln"
    synopsis = "ln -s target linkname"
    help_text = "Create a symbolic link (only -s symlinks are supported)."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        if "s" not in flags or len(operands) < 2:
            ctx.errorln("ln: usage: ln -s target linkname")
            return 1
        try:
            ctx.kernel.sys_symlink(operands[0], operands[1])
            return 0
        except FSError as e:
            ctx.errorln(f"ln: {e}")
            return 1


class Head(Command):
    name = "head"
    synopsis = "head [-n N] [file...]"
    help_text = "Output the first N lines (default 10)."

    def run(self, ctx):
        return _head_tail(ctx, head=True)


class Tail(Command):
    name = "tail"
    synopsis = "tail [-n N] [file...]"
    help_text = "Output the last N lines (default 10)."

    def run(self, ctx):
        return _head_tail(ctx, head=False)


def _head_tail(ctx, head):
    flags, values, operands = Command.parse_flags(ctx.argv[1:], valued=("n",))
    n = int(values.get("n", 10)) if str(values.get("n", "10")).lstrip("-").isdigit() else 10
    rc = 0
    sources = []
    if operands:
        for f in operands:
            try:
                sources.append(ctx.kernel.sys_open_read(f))
            except FSError as e:
                ctx.errorln(f"{'head' if head else 'tail'}: {e}")
                rc = 1
    else:
        sources.append(ctx.stdin)
    for data in sources:
        lines = data.splitlines(keepends=True)
        chunk = lines[:n] if head else lines[-n:]
        ctx.write("".join(chunk))
    return rc


class Grep(Command):
    name = "grep"
    synopsis = "grep [-i] [-n] [-v] pattern [file...]"
    help_text = ("Search for lines matching a pattern.\n"
                 "  -i  case-insensitive\n  -n  show line numbers\n"
                 "  -v  invert match")

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        if not operands:
            ctx.errorln("grep: missing pattern")
            return 1
        pattern = operands[0]
        files = operands[1:]
        ci = "i" in flags
        show_n = "n" in flags
        invert = "v" in flags
        needle = pattern.lower() if ci else pattern

        def scan(data, prefix=""):
            matched = False
            for idx, line in enumerate(data.splitlines(), 1):
                hay = line.lower() if ci else line
                hit = needle in hay
                if hit != invert:
                    matched = True
                    out = f"{prefix}{idx}:{line}" if show_n else f"{prefix}{line}"
                    ctx.writeln(out)
            return matched

        any_match = False
        rc = 0
        if files:
            multi = len(files) > 1
            for f in files:
                try:
                    data = ctx.kernel.sys_open_read(f)
                except FSError as e:
                    ctx.errorln(f"grep: {e}")
                    rc = 1
                    continue
                prefix = f"{f}:" if multi else ""
                if scan(data, prefix):
                    any_match = True
        else:
            any_match = scan(ctx.stdin)
        if rc:
            return rc
        return 0 if any_match else 1


class Find(Command):
    name = "find"
    synopsis = "find [path] [-name pattern] [-type f|d]"
    help_text = "Recursively search for files below a path."

    def run(self, ctx):
        args = ctx.argv[1:]
        start = "."
        if args and not args[0].startswith("-"):
            start = args[0]
            args = args[1:]
        name_pat = None
        type_filter = None
        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                name_pat = args[i + 1]
                i += 2
            elif args[i] == "-type" and i + 1 < len(args):
                type_filter = args[i + 1]
                i += 2
            else:
                i += 1
        try:
            node = ctx.kernel.sys_stat(start)
        except FSError as e:
            ctx.errorln(f"find: {e}")
            return 1
        base = ctx.kernel.fs.path_of(node) if start != "." else start
        if start == ".":
            base = "."
        self._walk(ctx, node, base, name_pat, type_filter)
        return 0

    def _walk(self, ctx, node, path, name_pat, type_filter):
        want = True
        if name_pat and not fnmatch.fnmatch(node.name or path, name_pat):
            want = False
        if type_filter == "f" and not node.is_file:
            want = False
        if type_filter == "d" and not node.is_dir:
            want = False
        if want:
            ctx.writeln(path)
        if node.is_dir:
            for name, child in sorted(node.children.items()):
                child_path = (path.rstrip("/") + "/" + name) if path != "/" else "/" + name
                self._walk(ctx, child, child_path, name_pat, type_filter)


class Tree(Command):
    name = "tree"
    synopsis = "tree [path]"
    help_text = "Display a directory tree."

    def run(self, ctx):
        path = ctx.argv[1] if len(ctx.argv) > 1 else "."
        try:
            node = ctx.kernel.sys_stat(path)
        except FSError as e:
            ctx.errorln(f"tree: {e}")
            return 1
        ctx.writeln(path)
        self._draw(ctx, node, "")
        return 0

    def _draw(self, ctx, node, prefix):
        if not node.is_dir:
            return
        entries = [(n, c) for n, c in sorted(node.children.items())
                   if not n.startswith(".")]
        for i, (name, child) in enumerate(entries):
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            suffix = "/" if child.is_dir else ("@ -> " + child.target if child.is_link else "")
            ctx.writeln(prefix + branch + name + (suffix if child.is_dir else ("" if not child.is_link else suffix)))
            if child.is_dir:
                self._draw(ctx, child, prefix + ("    " if last else "│   "))


class Chmod(Command):
    name = "chmod"
    synopsis = "chmod mode file..."
    help_text = ("Change file permission bits.\n"
                 "Accepts octal (755) or symbolic (u+x, go-w, a=rx) modes.")

    def run(self, ctx):
        _, _, operands = self.parse_flags(ctx.argv[1:])
        if len(operands) < 2:
            ctx.errorln("chmod: missing operand")
            return 1
        spec = operands[0]
        rc = 0
        for f in operands[1:]:
            try:
                node = ctx.kernel.sys_stat(f)
                mode = perm.parse_mode(spec, node.mode)
                ctx.kernel.sys_chmod(f, mode)
            except (FSError, ValueError) as e:
                ctx.errorln(f"chmod: {e}")
                rc = 1
        return rc


class Chown(Command):
    name = "chown"
    synopsis = "chown owner[:group] file..."
    help_text = "Change file owner and/or group (root only)."

    def run(self, ctx):
        _, _, operands = self.parse_flags(ctx.argv[1:])
        if len(operands) < 2:
            ctx.errorln("chown: missing operand")
            return 1
        spec = operands[0]
        owner, _, group = spec.partition(":")
        db = ctx.kernel.userdb
        uid = _resolve_uid(db, owner) if owner else None
        gid = _resolve_gid(db, group) if group else None
        if owner and uid is None:
            ctx.errorln(f"chown: invalid user: '{owner}'")
            return 1
        rc = 0
        for f in operands[1:]:
            try:
                ctx.kernel.sys_chown(f, uid=uid, gid=gid)
            except FSError as e:
                ctx.errorln(f"chown: {e}")
                rc = 1
        return rc


def _resolve_uid(db, name):
    if name.isdigit():
        return int(name)
    u = db.get_user(name)
    return u.uid if u else None


def _resolve_gid(db, name):
    if name.isdigit():
        return int(name)
    g = db.get_group(name=name)
    return g.gid if g else None


class Clear(Command):
    name = "clear"
    synopsis = "clear"
    help_text = "Clear the terminal screen."

    def run(self, ctx):
        ctx.write("\x1b[2J\x1b[H")
        return 0


class Whoami(Command):
    name = "whoami"
    synopsis = "whoami"
    help_text = "Print the current effective username."

    def run(self, ctx):
        ctx.writeln(ctx.session.username)
        return 0


class Hostname(Command):
    name = "hostname"
    synopsis = "hostname"
    help_text = "Show the system hostname."

    def run(self, ctx):
        ctx.writeln(ctx.session.hostname)
        return 0


class Uname(Command):
    name = "uname"
    synopsis = "uname [-a|-s|-n|-r|-m]"
    help_text = "Print system information."

    def run(self, ctx):
        k = ctx.kernel
        flags, _, _ = self.parse_flags(ctx.argv[1:])
        s = "MiniOS"
        n = ctx.session.hostname
        r = k.VERSION
        m = k.ARCH
        if "a" in flags:
            ctx.writeln(f"{s} {n} {r} {k.KERNEL_NAME} {m}")
        elif "n" in flags:
            ctx.writeln(n)
        elif "r" in flags:
            ctx.writeln(r)
        elif "m" in flags:
            ctx.writeln(m)
        else:
            ctx.writeln(s)
        return 0


class Env(Command):
    name = "env"
    aliases = ("printenv",)
    synopsis = "env"
    help_text = "Print environment variables."

    def run(self, ctx):
        for k, v in sorted(ctx.session.env.items()):
            ctx.writeln(f"{k}={v}")
        return 0


class Export(Command):
    name = "export"
    synopsis = "export NAME=value"
    help_text = "Set an environment variable."

    def run(self, ctx):
        if len(ctx.argv) == 1:
            for k, v in sorted(ctx.session.env.items()):
                ctx.writeln(f'declare -x {k}="{v}"')
            return 0
        for arg in ctx.argv[1:]:
            if "=" in arg:
                k, _, v = arg.partition("=")
                ctx.session.env[k] = v
        return 0


class Unset(Command):
    name = "unset"
    synopsis = "unset NAME"
    help_text = "Remove an environment variable."

    def run(self, ctx):
        for k in ctx.argv[1:]:
            ctx.session.env.pop(k, None)
        return 0


class History(Command):
    name = "history"
    synopsis = "history"
    help_text = "Show the command history for this session."

    def run(self, ctx):
        for i, line in enumerate(ctx.session.history, 1):
            ctx.writeln(f"{i:>5}  {line}")
        return 0


class Stat(Command):
    name = "stat"
    synopsis = "stat file"
    help_text = "Display detailed file status."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("stat: missing operand")
            return 1
        try:
            node = ctx.kernel.sys_stat(ctx.argv[1], follow=False)
        except FSError as e:
            ctx.errorln(f"stat: {e}")
            return 1
        ctx.writeln(f"  File: {ctx.argv[1]}")
        ctx.writeln(f"  Size: {node.size}\tInode: {node.ino}\t"
                    f"Type: {node.ftype}")
        octal = oct(node.mode & 0o7777)[2:].zfill(4)
        ctx.writeln(f"Access: ({octal}/{perm.mode_to_string(node.mode, node.ftype)})  "
                    f"Uid: ({node.uid}/{_uname(ctx, node.uid)})  "
                    f"Gid: ({node.gid}/{_gname(ctx, node.gid)})")
        ctx.writeln(f"Modify: {time.ctime(node.mtime)}")
        return 0


class Help(Command):
    name = "help"
    synopsis = "help [command]"
    help_text = "List available commands, or show help for one command."

    def run(self, ctx):
        reg = ctx.shell.registry
        if len(ctx.argv) > 1:
            name = ctx.argv[1]
            cmd = reg.get(name)
            if not cmd:
                ctx.errorln(f"help: no such command: {name}")
                return 1
            ctx.writeln(f"{cmd.name} — {cmd.synopsis}")
            ctx.writeln(cmd.help_text)
            return 0
        names = sorted({c.name for c in reg.values()})
        ctx.writeln("Available commands:")
        line = "  "
        for i, nm in enumerate(names):
            line += f"{nm:<12}"
            if (i + 1) % 5 == 0:
                ctx.writeln(line.rstrip())
                line = "  "
        if line.strip():
            ctx.writeln(line.rstrip())
        ctx.writeln("\nType 'man <command>' or '<command> --help' for details.")
        return 0


class Man(Command):
    name = "man"
    synopsis = "man command"
    help_text = "Show the manual page for a command."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("What manual page do you want?")
            return 1
        cmd = ctx.shell.registry.get(ctx.argv[1])
        if not cmd:
            ctx.errorln(f"No manual entry for {ctx.argv[1]}")
            return 1
        ctx.writeln(f"NAME\n    {cmd.name} — {cmd.synopsis.split()[0] if cmd.synopsis else cmd.name}")
        ctx.writeln(f"\nSYNOPSIS\n    {cmd.synopsis}")
        ctx.writeln("\nDESCRIPTION")
        for line in cmd.help_text.splitlines():
            ctx.writeln(f"    {line}")
        return 0


class Exit(Command):
    name = "exit"
    aliases = ("logout", "quit")
    synopsis = "exit"
    help_text = "Exit the shell and shut down the session."

    def run(self, ctx):
        # If we're inside an `su` session, exit returns to the previous user
        # rather than shutting the whole system down.
        if ctx.kernel.pop_session():
            return 0
        ctx.shell.request_exit = True
        return 0
