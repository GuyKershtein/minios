"""A single system service (unit)."""

from __future__ import annotations

import time


class Service:
    def __init__(self, name, description, proc=None, port=None, proto="tcp",
                 brings_up_iface=False, oneshot=False, enabled=False):
        self.name = name
        self.description = description
        self.proc = proc                    # long-running process name, if any
        self.port = port                    # listening port, if any
        self.proto = proto
        self.brings_up_iface = brings_up_iface
        self.oneshot = oneshot              # RemainAfterExit-style unit
        self.enabled = enabled
        self.active = False
        self.main_pid = None
        self.since = None

    @property
    def unit(self):
        return f"{self.name}.service"

    @property
    def sub(self):
        if not self.active:
            return "dead"
        return "exited" if self.oneshot else "running"

    def to_dict(self):
        return {"enabled": self.enabled, "active": self.active,
                "main_pid": self.main_pid, "since": self.since}

    def load_dict(self, d):
        self.enabled = d.get("enabled", self.enabled)
        self.active = d.get("active", self.active)
        self.main_pid = d.get("main_pid")
        self.since = d.get("since")
