"""Inode: the metadata + content record for every filesystem object."""

from __future__ import annotations

import time
from itertools import count

_ino_counter = count(1)


class Inode:
    """A filesystem object.

    ftype is one of: 'file', 'dir', 'link', 'char', 'block', 'fifo', 'socket'.
    - directories keep their entries in ``children`` (name -> Inode)
    - regular files keep their bytes in ``content`` (str)
    - symlinks keep their target path in ``target`` (str)
    """

    __slots__ = (
        "ino", "ftype", "mode", "uid", "gid",
        "content", "children", "target",
        "atime", "mtime", "ctime", "parent", "name",
    )

    def __init__(self, ftype="file", mode=0o644, uid=0, gid=0,
                 name="", parent=None):
        self.ino = next(_ino_counter)
        self.ftype = ftype
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.content = ""          # for files
        self.children = {}          # for dirs: name -> Inode
        self.target = ""            # for symlinks
        self.name = name
        self.parent = parent
        now = time.time()
        self.atime = now
        self.mtime = now
        self.ctime = now

    # -- convenience predicates ------------------------------------------
    @property
    def is_dir(self):
        return self.ftype == "dir"

    @property
    def is_file(self):
        return self.ftype == "file"

    @property
    def is_link(self):
        return self.ftype == "link"

    @property
    def size(self):
        if self.is_dir:
            return max(len(self.children) * 64, 4096)
        if self.is_link:
            return len(self.target)
        return len(self.content.encode("utf-8", errors="replace"))

    @property
    def nlink(self):
        if self.is_dir:
            # ., .., plus one per subdirectory
            return 2 + sum(1 for c in self.children.values() if c.is_dir)
        return 1

    def touch(self, mtime=True, atime=True):
        now = time.time()
        if atime:
            self.atime = now
        if mtime:
            self.mtime = now
            self.ctime = now

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        d = {
            "ino": self.ino,
            "ftype": self.ftype,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "name": self.name,
            "atime": self.atime,
            "mtime": self.mtime,
            "ctime": self.ctime,
        }
        if self.is_dir:
            d["children"] = {n: c.to_dict() for n, c in self.children.items()}
        elif self.is_link:
            d["target"] = self.target
        else:
            d["content"] = self.content
        return d

    @classmethod
    def from_dict(cls, d, parent=None):
        node = cls(ftype=d["ftype"], mode=d["mode"], uid=d["uid"],
                   gid=d["gid"], name=d.get("name", ""), parent=parent)
        node.ino = d.get("ino", node.ino)
        node.atime = d.get("atime", node.atime)
        node.mtime = d.get("mtime", node.mtime)
        node.ctime = d.get("ctime", node.ctime)
        if node.is_dir:
            for name, child_d in d.get("children", {}).items():
                node.children[name] = cls.from_dict(child_d, parent=node)
        elif node.is_link:
            node.target = d.get("target", "")
        else:
            node.content = d.get("content", "")
        return node

    def __repr__(self):
        return f"<Inode {self.ftype} {self.name!r} mode={oct(self.mode)}>"
