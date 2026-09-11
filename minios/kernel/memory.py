"""Simulated memory manager (RAM + swap).

Total RAM is fixed; "used" is derived from the kernel's reserved base plus the
sum of resident memory of all live processes, so memory really tracks process
activity (spawning a process consumes RAM; killing it frees RAM).
"""

from __future__ import annotations


class MemoryManager:
    def __init__(self, kernel, total_mb=4096, swap_mb=2048, base_mb=180):
        self.kernel = kernel
        self.total_kb = total_mb * 1024
        self.swap_total_kb = swap_mb * 1024
        self.base_kb = base_mb * 1024      # kernel + buffers/cache baseline
        self.swap_used_kb = 0

    def used_kb(self):
        proc_kb = self.kernel.procmgr.total_mem_kb() if \
            getattr(self.kernel, "procmgr", None) else 0
        used = self.base_kb + proc_kb
        # spill into swap if we exceed physical RAM
        if used > self.total_kb:
            self.swap_used_kb = min(used - self.total_kb, self.swap_total_kb)
            used = self.total_kb
        else:
            self.swap_used_kb = 0
        return used

    def free_kb(self):
        return max(self.total_kb - self.used_kb(), 0)

    def snapshot(self):
        used = self.used_kb()
        return {
            "total": self.total_kb,
            "used": used,
            "free": self.total_kb - used,
            "available": self.total_kb - used,
            "buffers": self.base_kb // 3,
            "cached": self.base_kb // 2,
            "swap_total": self.swap_total_kb,
            "swap_used": self.swap_used_kb,
            "swap_free": self.swap_total_kb - self.swap_used_kb,
        }

    def to_dict(self):
        return {"total_kb": self.total_kb, "swap_total_kb": self.swap_total_kb,
                "base_kb": self.base_kb}

    def load_dict(self, d):
        self.total_kb = d.get("total_kb", self.total_kb)
        self.swap_total_kb = d.get("swap_total_kb", self.swap_total_kb)
        self.base_kb = d.get("base_kb", self.base_kb)
