"""System information and storage commands: free, df, du, lsblk, blkid,
mount, umount, uptime, lscpu, who."""

from __future__ import annotations

import time

from ...filesystem import FSError
from .base import Command

GiB = 1024 ** 3
MiB = 1024 ** 2


def _hsize(nbytes):
    n = float(nbytes)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


class Free(Command):
    name = "free"
    synopsis = "free [-m|-g|-h]"
    help_text = "Display the amount of free and used memory."

    def run(self, ctx):
        flags, _, _ = self.parse_flags(ctx.argv[1:])
        m = ctx.kernel.memory.snapshot()

        def fmt(kb):
            if "h" in flags:
                return _hsize(kb * 1024)
            if "g" in flags:
                return f"{kb / 1024 / 1024:.1f}"
            return str(kb // 1024)  # default: MB

        unit = "" if "h" in flags else ("(GB)" if "g" in flags else "(MB)")
        ctx.writeln(f"{'':<10}{'total':>10}{'used':>10}{'free':>10}"
                    f"{'buffers':>10}{'cached':>10}   {unit}")
        ctx.writeln(f"{'Mem:':<10}{fmt(m['total']):>10}{fmt(m['used']):>10}"
                    f"{fmt(m['free']):>10}{fmt(m['buffers']):>10}"
                    f"{fmt(m['cached']):>10}")
        ctx.writeln(f"{'Swap:':<10}{fmt(m['swap_total']):>10}"
                    f"{fmt(m['swap_used']):>10}{fmt(m['swap_free']):>10}")
        return 0


class Df(Command):
    name = "df"
    synopsis = "df [-h]"
    help_text = "Report filesystem disk space usage for mounted partitions."

    def run(self, ctx):
        flags, _, _ = self.parse_flags(ctx.argv[1:])
        human = "h" in flags
        dm = ctx.kernel.disks

        def sz(n):
            return _hsize(n) if human else str(n // 1024)  # 1K blocks

        ctx.writeln(f"{'Filesystem':<14}{'Size':>8}{'Used':>8}{'Avail':>8}"
                    f"{'Use%':>6} Mounted on")
        for p in dm.mounted():
            used = dm.used_bytes(p)
            avail = max(p.size - used, 0)
            pct = int(100 * used / p.size) if p.size else 0
            ctx.writeln(f"{p.dev:<14}{sz(p.size):>8}{sz(used):>8}"
                        f"{sz(avail):>8}{str(pct) + '%':>6} {p.mountpoint}")
        return 0


class Du(Command):
    name = "du"
    synopsis = "du [-h] [-s] [path]"
    help_text = "Estimate file space usage. -s summarize, -h human-readable."

    def run(self, ctx):
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        human = "h" in flags
        summarize = "s" in flags
        path = operands[0] if operands else "."
        try:
            node = ctx.kernel.sys_stat(path)
        except FSError as e:
            ctx.errorln(f"du: {e}")
            return 1

        def size_of(n):
            total = n.size
            if n.is_dir:
                for c in n.children.values():
                    total += size_of(c)
            return total

        def blocks(nbytes):
            return _hsize(nbytes) if human else str(max(nbytes // 1024, 1))

        base = ctx.kernel.fs.path_of(node) if path == "." else path
        if summarize or not node.is_dir:
            ctx.writeln(f"{blocks(size_of(node))}\t{base}")
            return 0

        def walk(n, p):
            for name, child in sorted(n.children.items()):
                cp = (p.rstrip('/') + '/' + name)
                if child.is_dir:
                    walk(child, cp)
                    ctx.writeln(f"{blocks(size_of(child))}\t{cp}")
        walk(node, base)
        ctx.writeln(f"{blocks(size_of(node))}\t{base}")
        return 0


class Lsblk(Command):
    name = "lsblk"
    synopsis = "lsblk"
    help_text = "List block devices in a tree."

    def run(self, ctx):
        ctx.writeln(f"{'NAME':<8}{'SIZE':>7}  {'TYPE':<6}{'FSTYPE':<8}MOUNTPOINT")
        for disk in ctx.kernel.disks.disks:
            ctx.writeln(f"{disk.name:<8}{_hsize(disk.size):>7}  {'disk':<6}"
                        f"{'':<8}")
            for i, part in enumerate(disk.partitions):
                last = i == len(disk.partitions) - 1
                branch = "└─" if last else "├─"
                mp = part.mountpoint or ""
                ctx.writeln(f"{branch}{part.name:<6}{_hsize(part.size):>7}  "
                            f"{'part':<6}{part.fstype:<8}{mp}")
        return 0


class Blkid(Command):
    name = "blkid"
    synopsis = "blkid"
    help_text = "Show block device attributes (UUID, type)."

    def run(self, ctx):
        for p in ctx.kernel.disks.all_partitions():
            ctx.writeln(f'{p.dev}: UUID="{p.uuid()}" TYPE="{p.fstype}"')
        return 0


class Mount(Command):
    name = "mount"
    synopsis = "mount [device dir]"
    help_text = "Mount a filesystem, or list mounts when given no arguments."

    def run(self, ctx):
        args = ctx.argv[1:]
        if not args:
            for p in ctx.kernel.disks.mounted():
                ctx.writeln(f"{p.dev} on {p.mountpoint} type {p.fstype} "
                            f"(rw,relatime)")
            return 0
        if len(args) < 2:
            ctx.errorln("mount: usage: mount <device> <dir>")
            return 1
        if not self.require_root(ctx):
            return 1
        try:
            p = ctx.kernel.disks.mount(args[0], args[1])
            ctx.kernel.log("kernel", f"mounted {p.dev} on {p.mountpoint}")
        except ValueError as e:
            ctx.errorln(f"mount: {e}")
            return 1
        return 0


class Umount(Command):
    name = "umount"
    aliases = ("unmount",)
    synopsis = "umount device|dir"
    help_text = "Unmount a filesystem."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("umount: usage: umount <device|dir>")
            return 1
        if not self.require_root(ctx):
            return 1
        try:
            ctx.kernel.disks.umount(ctx.argv[1])
        except ValueError as e:
            ctx.errorln(f"umount: {e}")
            return 1
        return 0


class Uptime(Command):
    name = "uptime"
    synopsis = "uptime"
    help_text = "Show how long the system has been running."

    def run(self, ctx):
        secs = int(time.time() - ctx.kernel.boot_epoch)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        nproc = len(ctx.kernel.procmgr.all())
        now = time.strftime("%H:%M:%S")
        load = len([p for p in ctx.kernel.procmgr.all() if p.state == "R"])
        ctx.writeln(f" {now} up {h}h {m}m,  {nproc} tasks,  "
                    f"load average: 0.0{load}, 0.02, 0.00")
        return 0


class Lscpu(Command):
    name = "lscpu"
    synopsis = "lscpu"
    help_text = "Display information about the CPU architecture."

    def run(self, ctx):
        k = ctx.kernel
        cpus = k.procmgr.scheduler.cpus
        ctx.writeln(f"Architecture:        {k.ARCH}")
        ctx.writeln(f"CPU(s):              {cpus}")
        ctx.writeln("Vendor ID:           MiniOS")
        ctx.writeln(f"Model name:          MiniCPU {k.ARCH} @ 2.40GHz")
        ctx.writeln("CPU MHz:             2400.000")
        ctx.writeln(f"Scheduler policy:    {k.procmgr.scheduler.policy}")
        return 0


class Who(Command):
    name = "who"
    synopsis = "who"
    help_text = "Show who is logged in."

    def run(self, ctx):
        s = ctx.session
        login = time.strftime("%Y-%m-%d %H:%M", time.localtime(ctx.kernel.boot_epoch))
        ctx.writeln(f"{s.username:<10} tty1         {login}")
        return 0
