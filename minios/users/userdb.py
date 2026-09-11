"""The user database, backed by real files in the virtual filesystem.

``/etc/passwd``, ``/etc/group`` and ``/etc/shadow`` are the single source of
truth: this class parses them on read and rewrites them on mutation, so
``cat /etc/passwd`` always reflects reality and everything persists for free
via the Phase 1 filesystem serialization.
"""

from __future__ import annotations

from ..filesystem import FSError
from ..filesystem.filesystem import ROOT_CRED
from . import authentication as auth
from .users import Group, User

PASSWD = "/etc/passwd"
GROUP = "/etc/group"
SHADOW = "/etc/shadow"


class UserDBError(Exception):
    pass


class UserDB:
    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def fs(self):
        return self.kernel.fs

    # -- low-level file access -------------------------------------------
    def _read(self, path):
        try:
            return self.fs.read(path, "/", ROOT_CRED)
        except FSError:
            return ""

    def _write(self, path, data, mode):
        self.fs.write(path, "/", ROOT_CRED, data, mode=mode)
        try:
            self.fs.chmod(path, ROOT_CRED, mode)
        except FSError:
            pass

    # -- bootstrap --------------------------------------------------------
    def bootstrap_defaults(self):
        """Create the default accounts on a fresh system (idempotent)."""
        if self._read(PASSWD).strip():
            return
        users = [
            User("root", 0, 0, "root", "/root", "/bin/minish"),
            User("user", 1000, 1000, "Default User", "/home/user", "/bin/minish"),
        ]
        groups = [
            Group("root", 0, []),
            Group("user", 1000, []),
            Group("sudo", 27, ["user"]),
        ]
        self._write(PASSWD, "\n".join(u.passwd_line() for u in users) + "\n",
                    0o644)
        self._write(GROUP, "\n".join(g.group_line() for g in groups) + "\n",
                    0o644)
        # default passwords: root/root and user/user
        shadow_lines = [
            f"root:{auth.hash_password('root')}:19700:0:99999:7:::",
            f"user:{auth.hash_password('user')}:19700:0:99999:7:::",
        ]
        self._write(SHADOW, "\n".join(shadow_lines) + "\n", 0o640)

    # -- queries ----------------------------------------------------------
    def users(self):
        result = []
        for line in self._read(PASSWD).splitlines():
            if not line.strip():
                continue
            u = User.from_line(line)
            if u:
                result.append(u)
        return result

    def groups(self):
        result = []
        for line in self._read(GROUP).splitlines():
            if not line.strip():
                continue
            g = Group.from_line(line)
            if g:
                result.append(g)
        return result

    def get_user(self, name):
        for u in self.users():
            if u.name == name:
                return u
        return None

    def get_user_by_uid(self, uid):
        for u in self.users():
            if u.uid == uid:
                return u
        return None

    def get_group(self, name=None, gid=None):
        for g in self.groups():
            if (name is not None and g.name == name) or (gid is not None and g.gid == gid):
                return g
        return None

    def uname(self, uid):
        u = self.get_user_by_uid(uid)
        return u.name if u else str(uid)

    def gname(self, gid):
        g = self.get_group(gid=gid)
        return g.name if g else str(gid)

    def groups_of(self, username):
        """Return (primary_gid, [all gids]) for a user."""
        u = self.get_user(username)
        if not u:
            return (None, [])
        gids = [u.gid]
        for g in self.groups():
            if username in g.members and g.gid not in gids:
                gids.append(g.gid)
        return (u.gid, gids)

    def next_uid(self, system=False):
        uids = {u.uid for u in self.users()}
        start = 1 if system else 1000
        end = 1000 if system else 60000
        for candidate in range(start, end):
            if candidate not in uids:
                return candidate
        raise UserDBError("no free UID available")

    # -- authentication ---------------------------------------------------
    def shadow_hash(self, username):
        for line in self._read(SHADOW).splitlines():
            if line.startswith(username + ":"):
                return line.split(":")[1]
        return None

    def verify(self, username, password):
        stored = self.shadow_hash(username)
        if stored is None:
            return False
        return auth.verify_password(password, stored)

    # -- mutations --------------------------------------------------------
    def add_user(self, name, uid=None, gid=None, gecos="", home=None,
                 shell="/bin/minish", create_home=True):
        if self.get_user(name):
            raise UserDBError(f"user '{name}' already exists")
        if uid is None:
            uid = self.next_uid()
        if home is None:
            home = f"/home/{name}"
        # create a primary group with the same name if none specified
        if gid is None:
            grp = self.get_group(name=name)
            if grp:
                gid = grp.gid
            else:
                gid = uid
                self._append_group(Group(name, gid, []))
        user = User(name, uid, gid, gecos, home, shell)
        data = self._read(PASSWD).rstrip("\n")
        data = (data + "\n" if data else "") + user.passwd_line() + "\n"
        self._write(PASSWD, data, 0o644)
        # locked password until passwd is run
        sh = self._read(SHADOW).rstrip("\n")
        sh = (sh + "\n" if sh else "") + f"{name}:!:19700:0:99999:7:::\n"
        self._write(SHADOW, sh, 0o640)
        if create_home:
            self._make_home(user)
        return user

    def _make_home(self, user):
        try:
            self.fs.mkdir(user.home, ROOT_CRED, mode=0o755, parents=True,
                          exist_ok=True)
            self.fs.chown(user.home, ROOT_CRED, uid=user.uid, gid=user.gid)
        except FSError:
            pass

    def _append_group(self, group):
        data = self._read(GROUP).rstrip("\n")
        data = (data + "\n" if data else "") + group.group_line() + "\n"
        self._write(GROUP, data, 0o644)

    def del_user(self, name, remove_home=False):
        user = self.get_user(name)
        if not user:
            raise UserDBError(f"user '{name}' does not exist")
        self._write(PASSWD,
                    "".join(l + "\n" for l in self._read(PASSWD).splitlines()
                            if not l.startswith(name + ":")), 0o644)
        self._write(SHADOW,
                    "".join(l + "\n" for l in self._read(SHADOW).splitlines()
                            if not l.startswith(name + ":")), 0o640)
        # strip from group membership lists
        new_groups = []
        for g in self.groups():
            if name in g.members:
                g.members = [m for m in g.members if m != name]
            if not (g.name == name and not g.members):
                new_groups.append(g)
        self._write(GROUP, "".join(g.group_line() + "\n" for g in new_groups),
                    0o644)
        if remove_home:
            try:
                self.fs.remove(user.home, "/", ROOT_CRED, recursive=True)
            except FSError:
                pass

    def set_password(self, name, password):
        if not self.get_user(name):
            raise UserDBError(f"user '{name}' does not exist")
        hashed = auth.hash_password(password)
        out = []
        found = False
        for line in self._read(SHADOW).splitlines():
            if line.startswith(name + ":"):
                fields = line.split(":")
                fields[1] = hashed
                out.append(":".join(fields))
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{name}:{hashed}:19700:0:99999:7:::")
        self._write(SHADOW, "\n".join(out) + "\n", 0o640)

    def add_to_group(self, username, groupname):
        groups = self.groups()
        found = False
        for g in groups:
            if g.name == groupname:
                found = True
                if username not in g.members:
                    g.members.append(username)
        if not found:
            raise UserDBError(f"group '{groupname}' does not exist")
        self._write(GROUP, "".join(g.group_line() + "\n" for g in groups),
                    0o644)
