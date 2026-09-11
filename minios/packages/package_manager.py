"""The package manager.

Installed-package state lives in the virtual filesystem at
``/var/lib/minios/installed.json`` (so it is inspectable and persists for free).
Installing writes each package's files into the VFS and records them; removing
deletes exactly those files.
"""

from __future__ import annotations

import json

from ..filesystem import FSError
from ..filesystem.filesystem import ROOT_CRED
from .repository import Repository

DB_PATH = "/var/lib/minios/installed.json"
LISTS_PATH = "/var/lib/minios/lists"


class PackageError(Exception):
    pass


class PackageManager:
    def __init__(self, kernel):
        self.kernel = kernel
        self.repo = Repository()
        self._ensure_dirs()

    def _ensure_dirs(self):
        try:
            self.kernel.fs.mkdir("/var/lib/minios", ROOT_CRED, parents=True,
                                 exist_ok=True)
            if not self.kernel.fs.exists(DB_PATH):
                self.kernel.fs.write(DB_PATH, "/", ROOT_CRED, "{}")
        except FSError:
            pass

    # -- installed DB -----------------------------------------------------
    def _load_db(self):
        try:
            return json.loads(self.kernel.fs.read(DB_PATH, "/", ROOT_CRED))
        except (FSError, json.JSONDecodeError):
            return {}

    def _save_db(self, db):
        self.kernel.fs.write(DB_PATH, "/", ROOT_CRED, json.dumps(db))

    def is_installed(self, name):
        return name in self._load_db()

    def installed(self):
        return self._load_db()

    # -- operations -------------------------------------------------------
    def update(self):
        """Refresh package lists from the (simulated) repository."""
        import time
        self.kernel.fs.write(LISTS_PATH, "/", ROOT_CRED,
                             f"updated {time.ctime()}\n"
                             f"{len(self.repo.packages)} packages available\n")
        return [
            f"Hit:1 {self.repo.url} stable InRelease",
            f"Reading package lists... Done",
            f"{len(self.repo.packages)} packages available.",
        ]

    def _resolve(self, name, db, ordered):
        pkg = self.repo.get(name)
        if pkg is None:
            raise PackageError(f"Unable to locate package {name}")
        if name in db or name in ordered:
            return
        for dep in pkg.depends:
            self._resolve(dep, db, ordered)
        ordered.append(name)

    def install(self, name):
        db = self._load_db()
        if name not in self.repo.packages:
            raise PackageError(f"Unable to locate package {name}")
        if name in db:
            return {"already": True, "installed": [], "package": name}
        ordered = []
        self._resolve(name, db, ordered)
        installed_now = []
        for pkgname in ordered:
            pkg = self.repo.get(pkgname)
            written = []
            for path, (content, mode) in pkg.files.items():
                parent = path.rsplit("/", 1)[0] or "/"
                self.kernel.fs.mkdir(parent, ROOT_CRED, parents=True,
                                     exist_ok=True)
                self.kernel.fs.write(path, "/", ROOT_CRED, content, mode=mode)
                self.kernel.fs.chmod(path, ROOT_CRED, mode)
                written.append(path)
            db[pkgname] = {"version": pkg.version,
                           "description": pkg.description,
                           "files": written, "depends": pkg.depends}
            installed_now.append(pkgname)
        self._save_db(db)
        self.kernel.log("dpkg", f"install {name} "
                                f"({', '.join(installed_now)})")
        return {"already": False, "installed": installed_now, "package": name}

    def remove(self, name, purge=False):
        db = self._load_db()
        if name not in db:
            raise PackageError(f"Package '{name}' is not installed, so not removed")
        # refuse if another installed package depends on this one
        for other, meta in db.items():
            if other != name and name in meta.get("depends", []):
                raise PackageError(
                    f"error: dependency problem — {other} depends on {name}")
        for path in db[name].get("files", []):
            try:
                self.kernel.fs.remove(path, "/", ROOT_CRED)
            except FSError:
                pass
        del db[name]
        self._save_db(db)
        self.kernel.log("dpkg", f"remove {name}")
        return True
