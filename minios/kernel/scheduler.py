"""A simulated CPU scheduler.

Supports two policies:
  * round-robin ('rr')  — runnable processes each get a fixed time quantum
  * priority ('priority') — the runnable process with the best (lowest) nice
                            value runs; ties fall back to round-robin order

One ``tick`` == one unit of simulated CPU time (~1 second). Ticking advances
the running process's CPU time, retires finite jobs whose time has elapsed, and
rotates/repicks according to the policy. Foreground commands advance the clock
a little; ``sleep N`` advances it by N.
"""

from __future__ import annotations


class Scheduler:
    def __init__(self, manager, policy="rr", quantum=4, cpus=1):
        self.manager = manager
        self.policy = policy
        self.quantum = quantum
        self.cpus = cpus
        self.current = None       # pid currently on CPU 0
        self.quantum_left = quantum
        self.total_ticks = 0

    # -- queue ------------------------------------------------------------
    def ready_pids(self):
        return [p.pid for p in self.manager.all() if p.runnable]

    def _pick(self, exclude_current_rotate=True):
        ready = [self.manager.get(pid) for pid in self.ready_pids()]
        ready = [p for p in ready if p is not None]
        if not ready:
            return None
        if self.policy == "priority":
            ready.sort(key=lambda p: (p.nice, p.pid))
            return ready[0].pid
        # round robin: pick the next pid after current
        pids = [p.pid for p in ready]
        if self.current in pids and exclude_current_rotate:
            i = pids.index(self.current)
            return pids[(i + 1) % len(pids)]
        return pids[0]

    # -- run --------------------------------------------------------------
    def tick(self, n=1):
        for _ in range(n):
            self._one_tick()

    def _one_tick(self):
        self.total_ticks += 1
        # choose a process if none is running or quantum expired
        if self.current is None or self.manager.get(self.current) is None \
                or not self.manager.get(self.current).runnable:
            self.current = self._pick(exclude_current_rotate=False)
            self.quantum_left = self.quantum
        proc = self.manager.get(self.current) if self.current else None
        if proc is None:
            return
        # account CPU time
        proc.cpu_ticks += 1
        self.quantum_left -= 1
        # finite jobs count down and finish
        if proc.remaining is not None:
            proc.remaining -= 1
            if proc.remaining <= 0:
                self.manager.exit(proc.pid)
                self.current = None
                self.quantum_left = self.quantum
                return
        # round-robin preemption when the quantum runs out
        if self.policy == "rr" and self.quantum_left <= 0:
            nxt = self._pick(exclude_current_rotate=True)
            self.current = nxt
            self.quantum_left = self.quantum
        elif self.policy == "priority":
            # always re-evaluate the highest-priority runnable task
            self.current = self._pick(exclude_current_rotate=False)

    def snapshot(self):
        return {
            "policy": self.policy,
            "quantum": self.quantum,
            "cpus": self.cpus,
            "running": self.current,
            "queue": [pid for pid in self.ready_pids() if pid != self.current],
            "total_ticks": self.total_ticks,
        }

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {
            "policy": self.policy, "quantum": self.quantum, "cpus": self.cpus,
            "current": self.current, "quantum_left": self.quantum_left,
            "total_ticks": self.total_ticks,
        }

    def load_dict(self, d):
        self.policy = d.get("policy", self.policy)
        self.quantum = d.get("quantum", self.quantum)
        self.cpus = d.get("cpus", self.cpus)
        self.current = d.get("current")
        self.quantum_left = d.get("quantum_left", self.quantum)
        self.total_ticks = d.get("total_ticks", 0)
