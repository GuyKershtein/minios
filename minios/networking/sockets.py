"""Network sockets (as shown by ss / netstat)."""

from __future__ import annotations


class Socket:
    def __init__(self, proto, local_ip, local_port, state="LISTEN",
                 peer="*:*", program="", pid=None):
        self.proto = proto            # "tcp" / "udp"
        self.local_ip = local_ip
        self.local_port = local_port
        self.state = state            # LISTEN / ESTAB / ...
        self.peer = peer
        self.program = program
        self.pid = pid

    @property
    def local(self):
        return f"{self.local_ip}:{self.local_port}"

    def to_dict(self):
        return {"proto": self.proto, "local_ip": self.local_ip,
                "local_port": self.local_port, "state": self.state,
                "peer": self.peer, "program": self.program, "pid": self.pid}

    @classmethod
    def from_dict(cls, d):
        return cls(d["proto"], d["local_ip"], d["local_port"], d["state"],
                   d["peer"], d["program"], d["pid"])
