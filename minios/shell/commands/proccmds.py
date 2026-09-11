"""Process and scheduler commands: ps, top, htop, kill, killall, jobs, fg, bg,
renice, sleep, sched."""

from __future__ import annotations

import time

from ...kernel.process import SIGNAL_NAMES, SIGKILL, SIGTERM
from .base import Command

_STATE_WORDS = {
    "R": "RUNNING", "S": "SLEEPING", "T": "STOPPED", "Z": "ZOMBIE",
    "I": "IDLE", "READY": "READY",
}


class Ps(Command):
    name = "ps"
    synopsis = "ps [-e|-A] [-f] [aux]"
    help_text = ("Report process status.\n"
                 "  (no args)  all processes: PID USER STATE COMMAND\n"
                 "  -f         full format (UID PID PPID STIME TIME CMD)\n"
                 "  aux        BSD format with %CPU and %MEM")

    def run(self, ctx):
        raw = ctx.argv[1:]
        db = ctx.kernel.userdb
        procs = ctx.kernel.sys_ps()
        mode = "default"
        if "aux" in raw:
            mode = "aux"
        elif "-f" in raw or "-ef" in raw:
            mode = "full"

        if mode == "aux":
            total_mem = max(ctx.kernel.procmgr.total_mem_kb(), 1)
            total_ticks = max(ctx.kernel.procmgr.scheduler.total_ticks, 1)
            ctx.writeln(f"{'USER':<8}{'PID':>5} {'%CPU':>5} {'%MEM':>5} "
                        f"{'RSS':>7} {'STAT':<5}{'TIME':>7} COMMAND")
            for p in procs:
                cpu = 100.0 * p.cpu_ticks / total_ticks
                mem = 100.0 * p.mem_kb / total_mem
                ctx.writeln(f"{db.uname(p.uid):<8}{p.pid:>5} {cpu:>5.1f} "
                            f"{mem:>5.1f} {p.mem_kb:>7} {p.state:<5}"
                            f"{p.cpu_time_str():>7} {' '.join(p.argv)}")
        elif mode == "full":
            ctx.writeln(f"{'UID':<8}{'PID':>5}{'PPID':>6} {'STIME':>6} "
                        f"{'TIME':>7} CMD")
            for p in procs:
                st = time.strftime("%H:%M", time.localtime(p.start_epoch))
                ctx.writeln(f"{db.uname(p.uid):<8}{p.pid:>5}{p.ppid:>6} "
                            f"{st:>6} {p.cpu_time_str():>7} {' '.join(p.argv)}")
        else:
            ctx.writeln(f"{'PID':>5}  {'USER':<8} {'STATE':<9} COMMAND")
            for p in procs:
                ctx.writeln(f"{p.pid:>5}  {db.uname(p.uid):<8} "
                            f"{_STATE_WORDS.get(p.state, p.state):<9} "
                            f"{p.command}")
        return 0


class Top(Command):
    name = "top"
    aliases = ("htop",)
    synopsis = "top"
    help_text = "Show a one-shot snapshot of tasks, CPU and memory usage."

    def run(self, ctx):
        k = ctx.kernel
        db = k.userdb
        procs = k.sys_ps()
        sched = k.procmgr.scheduler
        uptime = int(time.time() - k.boot_epoch) if hasattr(k, "boot_epoch") else 0
        running = sum(1 for p in procs if p.state == "R")
        sleeping = sum(1 for p in procs if p.state == "S")
        stopped = sum(1 for p in procs if p.state == "T")
        mem = k.memory.snapshot() if hasattr(k, "memory") else None

        ctx.writeln(f"top - up {uptime}s,  {len(procs)} tasks,  "
                    f"policy={sched.policy}")
        ctx.writeln(f"Tasks: {len(procs)} total, {running} running, "
                    f"{sleeping} sleeping, {stopped} stopped")
        if mem:
            ctx.writeln(f"MiB Mem : {mem['total']//1024} total, "
                        f"{mem['free']//1024} free, {mem['used']//1024} used")
        ctx.writeln("")
        total_ticks = max(sched.total_ticks, 1)
        total_mem = max(k.procmgr.total_mem_kb(), 1)
        ctx.writeln(f"{'PID':>5} {'USER':<8}{'NI':>3} {'%CPU':>5} {'%MEM':>5} "
                    f"{'S':<2}{'TIME':>7} COMMAND")
        for p in sorted(procs, key=lambda x: -x.cpu_ticks):
            cpu = 100.0 * p.cpu_ticks / total_ticks
            memp = 100.0 * p.mem_kb / total_mem
            ctx.writeln(f"{p.pid:>5} {db.uname(p.uid):<8}{p.nice:>3} "
                        f"{cpu:>5.1f} {memp:>5.1f} {p.state:<2}"
                        f"{p.cpu_time_str():>7} {p.command}")
        return 0


class Kill(Command):
    name = "kill"
    synopsis = "kill [-SIG] pid..."
    help_text = ("Send a signal to a process (default TERM).\n"
                 "  -9 / -KILL   force kill\n  -STOP / -CONT   stop / continue")

    def run(self, ctx):
        args = ctx.argv[1:]
        sig = SIGTERM
        pids = []
        i = 0
        while i < len(args):
            a = args[i]
            if a.startswith("-") and len(a) > 1:
                key = a[1:]
                if key in ("s",) and i + 1 < len(args):
                    i += 1
                    key = args[i]
                sig = SIGNAL_NAMES.get(key.upper(), SIGNAL_NAMES.get(key, sig))
            else:
                pids.append(a)
            i += 1
        if not pids:
            ctx.errorln("kill: usage: kill [-SIG] pid...")
            return 1
        rc = 0
        for pid_s in pids:
            try:
                ctx.kernel.sys_kill(int(pid_s), sig)
            except ValueError:
                ctx.errorln(f"kill: illegal pid: {pid_s}")
                rc = 1
            except (KeyError, PermissionError) as e:
                ctx.errorln(f"kill: {e}")
                rc = 1
        return rc


class Killall(Command):
    name = "killall"
    synopsis = "killall [-9] name..."
    help_text = "Kill all processes matching a command name."

    def run(self, ctx):
        args = ctx.argv[1:]
        sig = SIGTERM
        names = []
        for a in args:
            if a.startswith("-"):
                sig = SIGNAL_NAMES.get(a[1:].upper(), SIGNAL_NAMES.get(a[1:], sig))
            else:
                names.append(a)
        rc = 0
        for name in names:
            n = ctx.kernel.procmgr.killall(name, sig)
            if n == 0:
                ctx.errorln(f"{name}: no process found")
                rc = 1
        return rc


class Jobs(Command):
    name = "jobs"
    synopsis = "jobs"
    help_text = "List background jobs started from this shell."

    def run(self, ctx):
        for p in ctx.kernel.procmgr.jobs():
            state = "Running" if p.state == "R" else _STATE_WORDS.get(p.state, p.state)
            ctx.writeln(f"[{p.job_id}]  {state:<10} {' '.join(p.argv)} "
                        f"(pid {p.pid})")
        return 0


class Fg(Command):
    name = "fg"
    synopsis = "fg [%job]"
    help_text = "Bring a background job to the foreground and wait for it."

    def run(self, ctx):
        p = _find_job(ctx, ctx.argv[1] if len(ctx.argv) > 1 else None)
        if not p:
            ctx.errorln("fg: no such job")
            return 1
        ctx.writeln(" ".join(p.argv))
        p.state = "R"
        # "wait": if the job is finite, run it to completion
        if p.remaining is not None:
            ctx.kernel.procmgr.scheduler.tick(p.remaining + ctx.kernel.procmgr.scheduler.quantum)
        return 0


class Bg(Command):
    name = "bg"
    synopsis = "bg [%job]"
    help_text = "Resume a stopped job in the background."

    def run(self, ctx):
        p = _find_job(ctx, ctx.argv[1] if len(ctx.argv) > 1 else None)
        if not p:
            ctx.errorln("bg: no such job")
            return 1
        p.state = "R"
        ctx.writeln(f"[{p.job_id}] {' '.join(p.argv)} &")
        return 0


def _find_job(ctx, spec):
    jobs = ctx.kernel.procmgr.jobs()
    if not jobs:
        return None
    if spec is None:
        return jobs[-1]
    spec = spec.lstrip("%")
    if spec.isdigit():
        jid = int(spec)
        for p in jobs:
            if p.job_id == jid:
                return p
    return None


class Renice(Command):
    name = "renice"
    synopsis = "renice N -p pid"
    help_text = "Change the priority (nice value) of a running process."

    def run(self, ctx):
        args = ctx.argv[1:]
        if len(args) < 1:
            ctx.errorln("renice: usage: renice N -p pid")
            return 1
        try:
            nice = int(args[0])
        except ValueError:
            ctx.errorln("renice: invalid nice value")
            return 1
        # accept both "renice 5 -p 42" and "renice 5 42"
        pid = None
        for a in args[1:]:
            if a.isdigit():
                pid = int(a)
        if pid is None:
            ctx.errorln("renice: no pid given")
            return 1
        p = ctx.kernel.procmgr.get(pid)
        if not p:
            ctx.errorln(f"renice: failed to set priority for {pid}: no such process")
            return 1
        if not ctx.session.is_root and nice < p.nice:
            ctx.errorln("renice: permission denied (only root may raise priority)")
            return 1
        p.nice = nice
        ctx.writeln(f"{pid}: old priority {p.nice}, new priority {nice}")
        return 0


class Sleep(Command):
    name = "sleep"
    synopsis = "sleep N"
    help_text = "Advance simulated time by N seconds (lets jobs make progress)."

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln("sleep: missing operand")
            return 1
        try:
            n = int(float(ctx.argv[1]))
        except ValueError:
            ctx.errorln(f"sleep: invalid time interval '{ctx.argv[1]}'")
            return 1
        ctx.kernel.procmgr.scheduler.tick(max(n, 0))
        return 0


class Sched(Command):
    name = "sched"
    synopsis = "sched [policy rr|priority] [tick N]"
    help_text = ("Inspect or drive the CPU scheduler.\n"
                 "  sched              show current state\n"
                 "  sched policy rr    switch to round-robin\n"
                 "  sched policy priority  switch to priority scheduling\n"
                 "  sched tick N       advance N ticks of simulated CPU time")

    def run(self, ctx):
        sched = ctx.kernel.procmgr.scheduler
        args = ctx.argv[1:]
        if args and args[0] == "policy" and len(args) > 1:
            pol = args[1]
            if pol not in ("rr", "priority"):
                ctx.errorln("sched: policy must be 'rr' or 'priority'")
                return 1
            sched.policy = pol
            ctx.writeln(f"scheduler policy set to {pol}")
            return 0
        if args and args[0] == "tick":
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
            sched.tick(n)
            ctx.writeln(f"advanced {n} tick(s)")
            return 0
        snap = sched.snapshot()
        db = ctx.kernel.userdb
        ctx.writeln(f"CPU 0  policy={snap['policy']}  quantum={snap['quantum']}  "
                    f"ticks={snap['total_ticks']}")
        run_pid = snap["running"]
        if run_pid is not None:
            p = ctx.kernel.procmgr.get(run_pid)
            label = f"{run_pid} ({p.command})" if p else str(run_pid)
            ctx.writeln(f"Running PID: {label}")
        else:
            ctx.writeln("Running PID: (idle)")
        ctx.writeln("Ready queue:")
        if snap["queue"]:
            for pid in snap["queue"]:
                p = ctx.kernel.procmgr.get(pid)
                ctx.writeln(f"  {pid:>5}  nice={p.nice:<3} {p.command}")
        else:
            ctx.writeln("  (empty)")
        return 0
