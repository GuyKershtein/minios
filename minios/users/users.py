"""User and Group records — thin data holders parsed from the passwd/group DB."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    name: str
    uid: int
    gid: int
    gecos: str = ""
    home: str = "/home"
    shell: str = "/bin/minish"

    def passwd_line(self):
        return f"{self.name}:x:{self.uid}:{self.gid}:{self.gecos}:{self.home}:{self.shell}"

    @classmethod
    def from_line(cls, line):
        parts = line.rstrip("\n").split(":")
        if len(parts) < 7:
            return None
        name, _pw, uid, gid, gecos, home, shell = parts[:7]
        try:
            return cls(name, int(uid), int(gid), gecos, home, shell)
        except ValueError:
            return None


@dataclass
class Group:
    name: str
    gid: int
    members: list = field(default_factory=list)

    def group_line(self):
        return f"{self.name}:x:{self.gid}:{','.join(self.members)}"

    @classmethod
    def from_line(cls, line):
        parts = line.rstrip("\n").split(":")
        if len(parts) < 4:
            # group with no members may render as 3 fields with trailing colon
            if len(parts) == 3:
                parts = parts + [""]
            else:
                return None
        name, _pw, gid, members = parts[:4]
        try:
            mem = [m for m in members.split(",") if m]
            return cls(name, int(gid), mem)
        except ValueError:
            return None
