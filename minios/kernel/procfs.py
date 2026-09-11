"""A dynamic /proc filesystem.

These paths are not stored as inodes — they are generated on demand from live
kernel state, so ``cat /proc/meminfo`` shows the current memory situation and
``cat /proc/<pid>/status`` reflects a real process in the table.
"""

from __future__ import annotations

import time

from ..filesystem import FSError
from ..filesystem.inode import Inode

_STATIC = ("cpuinfo", "meminfo", "uptime", "version", "loadavg", "mounts",
           "stat")


class ProcFS:
    def __init__(self, kernel):
        self.kernel = kernel

    def handles(self, abspath):
        return abspath == "/proc" or abspath.startswith("/proc/")

    # -- helpers ----------------------------------------------------------
    def _fake(self, name, ftype="file", content="", mode=0o444, uid=0):
        node = Inode(ftype=ftype, mode=mode, uid=uid, gid=0, name=name)
        node.content = content
        return node

    def _pids(self):
        return [p.pid for p in self.kernel.procmgr.all()]

    # -- listing ----------------------------------------------------------
    def listdir(self, abspath):
        parts = [s for s in abspath.split("/") if s]
        if abspath == "/proc":
            entries = [(n, self._fake(n)) for n in _STATIC]
            for pid in self._pids():
                entries.append((str(pid), self._fake(str(pid), "dir",
                                                     mode=0o555)))
            return sorted(entries, key=lambda e: (not e[0].isdigit(), e[0]))
        if len(parts) == 2 and parts[1].isdigit():
            pid = int(parts[1])
            if self.kernel.procmgr.get(pid) is None:
                raise FSError(f"no such file or directory: {abspath}")
            names = ["status", "cmdline", "stat", "cwd", "environ"]
            return [(n, self._fake(n)) for n in names]
        raise FSError(f"no such file or directory: {abspath}")

    def stat(self, abspath):
        parts = [s for s in abspath.split("/") if s]
        if abspath == "/proc":
            return self._fake("proc", "dir", mode=0o555)
        if len(parts) == 2:
            name = parts[1]
            if name in _STATIC:
                return self._fake(name)
            if name.isdigit() and self.kernel.procmgr.get(int(name)):
                return self._fake(name, "dir", mode=0o555)
        if len(parts) == 3 and parts[1].isdigit():
            return self._fake(parts[2])
        return None

    # -- content ----------------------------------------------------------
    def read(self, abspath):
        parts = [s for s in abspath.split("/") if s]
        if len(parts) == 2 and parts[1] in _STATIC:
            return getattr(self, f"_{parts[1]}")()
        if len(parts) == 3 and parts[1].isdigit():
            return self._pid_file(int(parts[1]), parts[2])
        raise FSError(f"{abspath}: No such file or directory")

    # -- generators -------------------------------------------------------
    def _meminfo(self):
        m = self.kernel.memory.snapshot()
        def kb(x):
            return f"{x:>8} kB"
        return (
            f"MemTotal:     {kb(m['total'])}\n"
            f"MemFree:      {kb(m['free'])}\n"
            f"MemAvailable: {kb(m['available'])}\n"
            f"Buffers:      {kb(m['buffers'])}\n"
            f"Cached:       {kb(m['cached'])}\n"
            f"SwapTotal:    {kb(m['swap_total'])}\n"
            f"SwapFree:     {kb(m['swap_free'])}\n"
        )

    def _cpuinfo(self):
        cpus = self.kernel.procmgr.scheduler.cpus
        out = []
        for i in range(cpus):
            out.append(
                f"processor\t: {i}\n"
                f"vendor_id\t: MiniOS\n"
                f"model name\t: MiniCPU {self.kernel.ARCH} @ 2.40GHz\n"
                f"cpu MHz\t\t: 2400.000\n"
                f"cache size\t: 4096 KB\n"
            )
        return "\n".join(out) + "\n"

    def _uptime(self):
        up = time.time() - self.kernel.boot_epoch
        return f"{up:.2f} {up * 0.9:.2f}\n"

    def _version(self):
        return (f"MiniOS version {self.kernel.VERSION} "
                f"({self.kernel.KERNEL_NAME}) {self.kernel.ARCH}\n")

    def _loadavg(self):
        n = len([p for p in self.kernel.procmgr.all() if p.state == "R"])
        return f"0.0{n} 0.0{n} 0.0{n} {n}/{len(self.kernel.procmgr.all())} " \
               f"{self.kernel.procmgr.next_pid}\n"

    def _mounts(self):
        lines = []
        for p in self.kernel.disks.mounted():
            lines.append(f"{p.dev} {p.mountpoint} {p.fstype} rw,relatime 0 0")
        return "\n".join(lines) + "\n"

    def _stat(self):
        return (f"cpu  0 0 0 0 0 0 0\n"
                f"ctxt {self.kernel.procmgr.scheduler.total_ticks}\n"
                f"processes {self.kernel.procmgr.next_pid}\n"
                f"btime {int(self.kernel.boot_epoch)}\n")

    def _pid_file(self, pid, fname):
        p = self.kernel.procmgr.get(pid)
        if not p:
            raise FSError(f"/proc/{pid}: No such process")
        if fname == "cmdline":
            return "\0".join(p.argv) + "\n"
        if fname == "cwd":
            return "/\n"
        if fname == "environ":
            return "PATH=/usr/bin:/bin\0"
        if fname == "stat":
            return f"{p.pid} ({p.command}) {p.state} {p.ppid} {p.cpu_ticks}\n"
        # status (default)
        return (
            f"Name:\t{p.command}\n"
            f"State:\t{p.state}\n"
            f"Pid:\t{p.pid}\n"
            f"PPid:\t{p.ppid}\n"
            f"Uid:\t{p.uid}\t{p.uid}\t{p.uid}\t{p.uid}\n"
            f"VmRSS:\t{p.mem_kb} kB\n"
            f"Nice:\t{p.nice}\n"
        )
