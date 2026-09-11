"""Processes and the process table.

Processes are simulated records with the fields a real ``ps`` shows: pid, ppid,
uid, command, state, cpu time, memory, priority (nice) and start time. The
kernel seeds ``init`` (pid 1) and a couple of kernel threads at boot; the shell
registers itself; background jobs (``cmd &``) create finite processes that the
scheduler advances over simulated time.

States (Linux-style single letters):
    R running    S sleeping    T stopped    Z zombie    I idle
"""

from __future__ import annotations

import time

# signal numbers we understand
SIGHUP = 1
SIGINT = 2
SIGKILL = 9
SIGTERM = 15
SIGSTOP = 19
SIGCONT = 18

SIGNAL_NAMES = {
    "HUP": SIGHUP, "INT": SIGINT, "KILL": SIGKILL, "TERM": SIGTERM,
    "STOP": SIGSTOP, "CONT": SIGCONT,
    "1": SIGHUP, "2": SIGINT, "9": SIGKILL, "15": SIGTERM,
    "18": SIGCONT, "19": SIGSTOP,
}


class Process:
    def __init__(self, pid, ppid, uid, command, argv=None, state="S",
                 nice=0, mem_kb=2048, remaining=None):
        self.pid = pid
        self.ppid = ppid
        self.uid = uid
        self.command = command
        self.argv = argv or [command]
        self.state = state
        self.nice = nice            # priority: lower = higher priority
        self.mem_kb = mem_kb
        self.start_epoch = time.time()
        self.cpu_ticks = 0          # accumulated scheduler ticks
        self.remaining = remaining  # finite jobs: ticks left; None = persistent
        self.job_id = None

    @property
    def runnable(self):
        return self.state in ("R", "READY")

    def cpu_time_str(self):
        secs = self.cpu_ticks
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def to_dict(self):
        return {
            "pid": self.pid, "ppid": self.ppid, "uid": self.uid,
            "command": self.command, "argv": self.argv, "state": self.state,
            "nice": self.nice, "mem_kb": self.mem_kb,
            "start_epoch": self.start_epoch, "cpu_ticks": self.cpu_ticks,
            "remaining": self.remaining, "job_id": self.job_id,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d["pid"], d["ppid"], d["uid"], d["command"], d["argv"],
                d["state"], d["nice"], d["mem_kb"], d["remaining"])
        p.start_epoch = d["start_epoch"]
        p.cpu_ticks = d["cpu_ticks"]
        p.job_id = d.get("job_id")
        return p


class ProcessManager:
    def __init__(self, kernel):
        self.kernel = kernel
        self.table = {}
        self.next_pid = 1
        self.next_job = 1
        from .scheduler import Scheduler
        self.scheduler = Scheduler(self)

    # -- lifecycle --------------------------------------------------------
    def seed(self):
        """Create the initial process tree on a fresh boot."""
        if self.table:
            return
        self._new(ppid=0, uid=0, command="init", state="S", mem_kb=1024)
        self._new(ppid=1, uid=0, command="kthreadd", state="S", mem_kb=0)
        self._new(ppid=1, uid=0, command="systemd-journald", state="S",
                  mem_kb=8192)

    def _new(self, ppid, uid, command, argv=None, state="S", nice=0,
             mem_kb=2048, remaining=None):
        pid = self.next_pid
        self.next_pid += 1
        p = Process(pid, ppid, uid, command, argv, state, nice, mem_kb,
                    remaining)
        self.table[pid] = p
        return p

    def spawn(self, command, argv=None, uid=None, ppid=1, nice=0,
              mem_kb=4096, remaining=None, state="R", background=False):
        if uid is None:
            uid = self.kernel.session.uid
        p = self._new(ppid, uid, command, argv, state, nice, mem_kb, remaining)
        if background:
            p.job_id = self.next_job
            self.next_job += 1
        return p

    # -- syscalls (simplified) -------------------------------------------
    def fork(self, parent_pid):
        parent = self.table.get(parent_pid)
        if not parent:
            raise KeyError(f"no such process: {parent_pid}")
        child = self._new(parent_pid, parent.uid, parent.command,
                          list(parent.argv), "R", parent.nice, parent.mem_kb)
        return child

    def execp(self, pid, command, argv=None):
        p = self.table.get(pid)
        if not p:
            raise KeyError(f"no such process: {pid}")
        p.command = command
        p.argv = argv or [command]
        return p

    def exit(self, pid, status=0):
        p = self.table.get(pid)
        if not p:
            return
        # reparent children to init (pid 1)
        for other in self.table.values():
            if other.ppid == pid:
                other.ppid = 1
        self.table.pop(pid, None)

    def kill(self, pid, sig=SIGTERM):
        p = self.table.get(pid)
        if not p:
            raise KeyError(f"({pid}) - No such process")
        if pid == 1:
            raise PermissionError("operation not permitted (cannot kill init)")
        # permission: normal users may only signal their own processes
        sess = self.kernel.session
        if not sess.is_root and p.uid != sess.uid:
            raise PermissionError("operation not permitted")
        if sig == SIGSTOP:
            p.state = "T"
        elif sig == SIGCONT:
            p.state = "R"
        else:  # TERM, KILL, HUP, INT -> terminate
            self.exit(pid)
        return True

    def killall(self, name, sig=SIGTERM):
        killed = 0
        for pid in [p.pid for p in self.table.values() if p.command == name]:
            try:
                self.kill(pid, sig)
                killed += 1
            except (KeyError, PermissionError):
                pass
        return killed

    # -- queries ----------------------------------------------------------
    def get(self, pid):
        return self.table.get(pid)

    def all(self):
        return [self.table[p] for p in sorted(self.table)]

    def jobs(self):
        return [p for p in self.all() if p.job_id is not None]

    def total_mem_kb(self):
        return sum(p.mem_kb for p in self.table.values())

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {
            "next_pid": self.next_pid,
            "next_job": self.next_job,
            "procs": [p.to_dict() for p in self.all()],
            "scheduler": self.scheduler.to_dict(),
        }

    def load_dict(self, d):
        self.table = {}
        for pd in d.get("procs", []):
            p = Process.from_dict(pd)
            self.table[p.pid] = p
        self.next_pid = d.get("next_pid", max(self.table, default=0) + 1)
        self.next_job = d.get("next_job", 1)
        self.scheduler.load_dict(d.get("scheduler", {}))
