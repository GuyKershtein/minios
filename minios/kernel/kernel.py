"""The Kernel — the central coordinator and syscall layer.

Everything else in the system talks to the kernel; the kernel owns the
subsystems and enforces policy. In Phase 1 it owns the FileSystem and the
active Session, plus a simplified system-call layer that commands use instead
of poking at subsystem internals directly. Later phases hang additional
managers (processes, memory, disks, network, services, packages) off the same
kernel object.
"""

from __future__ import annotations

import json
import os
import time

from ..filesystem import FileSystem
from ..session import Session
from ..users import UserDB
from .process import ProcessManager
from .memory import MemoryManager
from .disks import DiskManager
from .procfs import ProcFS
from .devices import DevFS
from ..networking import NetworkManager
from ..packages import PackageManager
from ..services import ServiceManager


class Kernel:
    VERSION = "1.0"
    ARCH = "x86_64"
    KERNEL_NAME = "MiniKernel"
    HOSTNAME = "minios"

    def __init__(self, statefile=None):
        self.statefile = statefile
        self.boot_epoch = time.time()
        self.reboot_requested = False
        self.fs = FileSystem()
        self.userdb = UserDB(self)
        self.boot_messages = []
        self._session_stack = []
        # Set by the terminal so interactive commands (su, passwd, login) can
        # read a line / a hidden password. None in non-interactive contexts.
        self.password_prompt = None
        self.line_prompt = None
        self._seed_config_files()
        self.userdb.bootstrap_defaults()
        self.session = self.make_session("user")
        self.procmgr = ProcessManager(self)
        self.procmgr.seed()
        self.shell_pid = self.procmgr.spawn(
            "minish", ["-minish"], uid=self.session.uid, ppid=1,
            mem_kb=6144, state="S").pid
        self.memory = MemoryManager(self)
        self.disks = DiskManager(self)
        self.procfs = ProcFS(self)
        self.devfs = DevFS(self)
        self.net = NetworkManager(self)
        self.pkg = PackageManager(self)
        self.services = ServiceManager(self)
        self.log("kernel", f"MiniOS {self.VERSION} booting on {self.ARCH}")
        self.log("syslog", "systemd: reached target Basic System.")
        self.services.start_enabled()

    # -- bootstrap config -------------------------------------------------
    def _seed_config_files(self):
        """Create the handful of config files Phase 1 relies on."""
        from ..filesystem.filesystem import ROOT_CRED
        try:
            self.fs.write("/etc/hostname", "/", ROOT_CRED,
                          self.HOSTNAME + "\n")
            self.fs.write("/etc/os-release", "/", ROOT_CRED,
                          'NAME="MiniOS"\nVERSION="1.0"\nID=minios\n'
                          'PRETTY_NAME="MiniOS 1.0"\n')
            self.fs.write("/etc/motd", "/", ROOT_CRED,
                          "Welcome to MiniOS 1.0 — a Linux simulator.\n")
            self.fs.write("/etc/hosts", "/", ROOT_CRED,
                          "127.0.0.1\tlocalhost\n"
                          f"127.0.1.1\t{self.HOSTNAME}\n"
                          "192.168.1.1\tgateway\n")
            # a couple of starter files in the user's home
            self.fs.write("/home/user/notes.txt", "/", ROOT_CRED,
                          "Welcome to MiniOS!\nTry: ls, cd, cat, echo, help\n")
            self.fs.chown("/home/user/notes.txt", ROOT_CRED, uid=1000, gid=1000)
            for d in ("Documents", "Downloads"):
                self.fs.mkdir(f"/home/user/{d}", ROOT_CRED, exist_ok=True)
                self.fs.chown(f"/home/user/{d}", ROOT_CRED, uid=1000, gid=1000)
            # device nodes (real inodes so `ls /dev` works; behaviour is in DevFS)
            for name, ftype, mode in (
                ("null", "char", 0o666), ("zero", "char", 0o666),
                ("full", "char", 0o666), ("random", "char", 0o666),
                ("urandom", "char", 0o666), ("tty", "char", 0o666),
                ("sda", "block", 0o660), ("sda1", "block", 0o660),
                ("sda2", "block", 0o660), ("sdb", "block", 0o660),
                ("sdb1", "block", 0o660),
            ):
                self.fs.mknod(f"/dev/{name}", ROOT_CRED, ftype=ftype, mode=mode)
        except Exception:
            pass

    # -- users / sessions / auth -----------------------------------------
    def make_session(self, username, login=True):
        user = self.userdb.get_user(username)
        if user is None:
            raise KeyError(f"no such user: {username}")
        _, gids = self.userdb.groups_of(username)
        sess = Session(self, username=user.name, uid=user.uid, gid=user.gid,
                       gids=tuple(gids), home=user.home, shell=user.shell,
                       hostname=self.HOSTNAME)
        sess.cwd = user.home
        sess.env["PWD"] = user.home
        return sess

    def authenticate(self, username, password):
        ok = self.userdb.verify(username, password)
        if ok:
            self.log("auth", f"authentication success for user {username}")
        else:
            self.log("auth", f"authentication failure for user {username}")
        return ok

    def switch_user(self, username, login=False):
        """Push the current session and become ``username`` (used by su)."""
        new = self.make_session(username, login=login)
        if not login:
            # non-login su keeps the current working directory if reachable
            try:
                from ..filesystem.filesystem import ROOT_CRED
                self.fs.resolve(self.session.cwd, "/", ROOT_CRED)
                new.cwd = self.session.cwd
                new.env["PWD"] = new.cwd
            except Exception:
                pass
        self._session_stack.append(self.session)
        self.session = new
        self.log("auth", f"session opened for user {username}")

    def pop_session(self):
        """Return to the previous session (from su). True if one existed."""
        if self._session_stack:
            self.log("auth", f"session closed for user {self.session.username}")
            self.session = self._session_stack.pop()
            return True
        return False

    def log(self, facility, message):
        from ..filesystem.filesystem import ROOT_CRED
        from ..filesystem import FSError
        # syslog uses the conventional name without a .log suffix
        path = "/var/log/syslog" if facility == "syslog" \
            else f"/var/log/{facility}.log"
        ts = time.strftime("%b %e %H:%M:%S")
        line = f"{ts} {self.HOSTNAME} {message}\n"
        try:
            self.fs.write(path, "/", ROOT_CRED, line, append=True, create=True)
        except FSError:
            pass

    # -- process syscalls -------------------------------------------------
    def sys_ps(self):
        return self.procmgr.all()

    def sys_spawn(self, command, argv=None, **kw):
        return self.procmgr.spawn(command, argv, **kw)

    def sys_kill(self, pid, sig=15):
        return self.procmgr.kill(pid, sig)

    def sys_tick(self, n=1):
        self.procmgr.scheduler.tick(n)

    # -- syscall layer ----------------------------------------------------
    # These are the ONLY entry points commands should use to touch the FS.
    def _cred(self):
        return self.session.cred()

    def abspath(self, path):
        """Normalize a path (relative to cwd) without requiring it to exist."""
        if not path.startswith("/"):
            path = self.session.cwd.rstrip("/") + "/" + path
        parts = []
        for seg in path.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(seg)
        return "/" + "/".join(parts)

    def sys_readdir(self, path):
        ap = self.abspath(path)
        if self.procfs.handles(ap):
            try:
                return self.procfs.listdir(ap)
            except Exception:
                pass
        return self.fs.listdir(path, self.session.cwd, self._cred())

    def sys_stat(self, path, follow=True):
        ap = self.abspath(path)
        if self.procfs.handles(ap):
            node = self.procfs.stat(ap)
            if node is not None:
                return node
        return self.fs.stat(path, self.session.cwd, self._cred(), follow=follow)

    def sys_open_read(self, path):
        ap = self.abspath(path)
        if self.procfs.handles(ap):
            return self.procfs.read(ap)
        if self.devfs.handles_read(ap):
            return self.devfs.read(ap)
        return self.fs.read(path, self.session.cwd, self._cred())

    def sys_write(self, path, data, append=False, create=True):
        ap = self.abspath(path)
        if self.devfs.handles_write(ap):
            return self.devfs.write(ap, data)
        return self.fs.write(path, self.session.cwd, self._cred(), data,
                             append=append, create=create)

    def sys_mkdir(self, path, mode=0o755, parents=False):
        return self.fs.mkdir(path, self._cred(), mode=mode, parents=parents,
                             cwd=self.session.cwd)

    def sys_create(self, path):
        return self.fs.create(path, self.session.cwd, self._cred())

    def sys_unlink(self, path, recursive=False):
        return self.fs.remove(path, self.session.cwd, self._cred(),
                              recursive=recursive)

    def sys_rmdir(self, path):
        return self.fs.rmdir(path, self.session.cwd, self._cred())

    def sys_rename(self, src, dst):
        return self.fs.move(src, dst, self.session.cwd, self._cred())

    def sys_copy(self, src, dst, recursive=False):
        return self.fs.copy(src, dst, self.session.cwd, self._cred(),
                            recursive=recursive)

    def sys_chmod(self, path, mode):
        return self.fs.chmod(path, self._cred(), mode, cwd=self.session.cwd)

    def sys_chown(self, path, uid=None, gid=None):
        return self.fs.chown(path, self._cred(), uid=uid, gid=gid,
                             cwd=self.session.cwd)

    def sys_symlink(self, target, linkpath):
        return self.fs.symlink(target, linkpath, self.session.cwd, self._cred())

    def sys_chdir(self, path):
        node = self.fs.resolve(path, self.session.cwd, self._cred())
        if not node.is_dir:
            from ..filesystem import FSError
            raise FSError(f"not a directory: {path}")
        from ..filesystem.permissions import can, X
        if not can(node, X, self.session.uid, self.session.gids):
            from ..filesystem import FSError
            raise FSError(f"permission denied: {path}")
        self.session.cwd = self.fs.path_of(node)
        self.session.env["PWD"] = self.session.cwd
        return self.session.cwd

    def sys_realpath(self, path):
        node = self.fs.resolve(path, self.session.cwd, self._cred())
        return self.fs.path_of(node)

    # -- persistence ------------------------------------------------------
    def save(self, path=None):
        path = path or self.statefile
        if not path:
            return False
        state = {
            "version": self.VERSION,
            "fs": self.fs.to_dict(),
            "session": self.session.to_dict(),
            "procs": self.procmgr.to_dict(),
            "memory": self.memory.to_dict(),
            "disks": self.disks.to_dict(),
            "net": self.net.to_dict(),
            "services": self.services.to_dict(),
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # write to a temp file then atomically replace, so an interrupted save
        # can never corrupt the existing state file
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True

    def load(self, path=None):
        path = path or self.statefile
        if not path or not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.fs = FileSystem.from_dict(state["fs"])
        self.session = Session(self)
        self.session.load_dict(state["session"])
        self.procmgr = ProcessManager(self)
        if "procs" in state:
            self.procmgr.load_dict(state["procs"])
        else:
            self.procmgr.seed()
        self.memory = MemoryManager(self)
        self.memory.load_dict(state.get("memory", {}))
        self.disks = DiskManager(self)
        self.disks.load_dict(state.get("disks", {}))
        self.procfs = ProcFS(self)
        self.devfs = DevFS(self)
        self.net = NetworkManager(self)
        self.pkg = PackageManager(self)
        self.net.load_dict(state.get("net", {}))
        self.services = ServiceManager(self)
        self.services.load_dict(state.get("services", {}))
        return True
