"""A local package repository.

The repository is a built-in catalogue of packages. Each package declares its
version, description, dependencies and the files it installs into the virtual
filesystem. Installing a package really writes those files; removing it deletes
them.
"""

from __future__ import annotations


class Package:
    def __init__(self, name, version, description, depends=None, files=None,
                 section="utils"):
        self.name = name
        self.version = version
        self.description = description
        self.depends = depends or []
        self.files = files or {}       # path -> (content, mode)
        self.section = section

    @property
    def size(self):
        return sum(len(c) for c, _ in self.files.values()) + 1024


def _bin(name, body):
    """Helper: a /usr/bin script for a package."""
    return {f"/usr/bin/{name}": (f"#!/bin/minish\n{body}\n", 0o755)}


def _default_packages():
    pkgs = [
        Package("nano", "6.2", "small, friendly text editor",
                files=_bin("nano", 'echo "GNU nano — use the built-in editor"'),
                section="editors"),
        Package("vim", "8.2", "Vi IMproved - enhanced vi editor",
                files=_bin("vim", 'echo "vim"'), section="editors"),
        Package("htop", "3.0", "interactive process viewer",
                files=_bin("htop", "top"), section="admin"),
        Package("cowsay", "3.03", "configurable talking cow",
                files=_bin("cowsay",
                           'echo " ___"\necho "< $* >"\necho " ---"\n'
                           'echo "    \\\\  ^__^"\necho "     \\\\ (oo)"'),
                section="games"),
        Package("curl", "7.81", "command line tool for transferring data",
                files=_bin("curl", 'echo "curl: (simulated) $*"'),
                section="net"),
        Package("git", "2.34", "distributed version control system",
                depends=["curl"],
                files=_bin("git", 'echo "git version 2.34.1 (MiniOS)"'),
                section="vcs"),
        Package("python3", "3.11", "interactive high-level language",
                files=_bin("python3", 'echo "Python 3.11.0 (MiniOS)"'),
                section="python"),
        Package("hello", "2.10", "friendly greeting program",
                files=_bin("hello", 'echo "Hello, world!"'), section="utils"),
        Package("tree", "2.0", "displays directories as trees (pkg wrapper)",
                files=_bin("tree-pkg", "tree $*"), section="utils"),
        Package("neofetch", "7.1", "shows system information with an ASCII logo",
                depends=[],
                files=_bin("neofetch",
                           'echo "MiniOS 1.0"\nuname -a\nfree\n'),
                section="admin"),
    ]
    return {p.name: p for p in pkgs}


class Repository:
    def __init__(self):
        self.packages = _default_packages()
        self.url = "http://packages.minios.local/stable"

    def get(self, name):
        return self.packages.get(name)

    def all(self):
        return [self.packages[n] for n in sorted(self.packages)]

    def search(self, term):
        term = term.lower()
        return [p for p in self.all()
                if term in p.name.lower() or term in p.description.lower()]
