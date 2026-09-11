"""Session state: who is logged in, where they are, and their environment.

In Phase 1 there is a single built-in ``user`` account plus ``root``. Phase 2
replaces the hard-wired users with a real /etc/passwd-backed user database.
"""

from __future__ import annotations


class Session:
    def __init__(self, kernel, username="user", uid=1000, gid=1000,
                 gids=(1000,), home="/home/user", shell="/bin/minish",
                 hostname="minios"):
        self.kernel = kernel
        self.username = username
        self.uid = uid
        self.gid = gid
        self.gids = tuple(gids)
        self.home = home
        self.shell = shell
        self.hostname = hostname
        self.cwd = home
        self.history = []
        self.env = {
            "HOME": home,
            "USER": username,
            "LOGNAME": username,
            "PATH": "/usr/local/bin:/usr/bin:/bin:/sbin",
            "PWD": home,
            "SHELL": shell,
            "HOSTNAME": hostname,
            "TERM": "minios",
            "LANG": "C.UTF-8",
            "PS1": r"\u@\h:\w\$ ",
        }

    @property
    def is_root(self):
        return self.uid == 0

    def cred(self):
        """Credentials object consumed by the filesystem layer."""
        return self

    def display_cwd(self):
        """~-abbreviated cwd for the prompt."""
        if self.cwd == self.home:
            return "~"
        if self.cwd.startswith(self.home + "/"):
            return "~" + self.cwd[len(self.home):]
        return self.cwd

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {
            "username": self.username,
            "uid": self.uid,
            "gid": self.gid,
            "gids": list(self.gids),
            "home": self.home,
            "shell": self.shell,
            "hostname": self.hostname,
            "cwd": self.cwd,
            "env": dict(self.env),
            "history": list(self.history)[-500:],
        }

    def load_dict(self, d):
        self.username = d.get("username", self.username)
        self.uid = d.get("uid", self.uid)
        self.gid = d.get("gid", self.gid)
        self.gids = tuple(d.get("gids", self.gids))
        self.home = d.get("home", self.home)
        self.shell = d.get("shell", self.shell)
        self.hostname = d.get("hostname", self.hostname)
        self.cwd = d.get("cwd", self.cwd)
        self.env.update(d.get("env", {}))
        self.history = list(d.get("history", []))
