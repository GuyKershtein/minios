"""Simulated block devices, partitions and mounts.

Disks and partitions are pure simulation. The root partition's *used* space is
derived from the real size of everything in the virtual filesystem, so ``df``
and ``du`` reflect actual file contents; other partitions carry a simulated
usage figure.
"""

from __future__ import annotations

import hashlib

GiB = 1024 ** 3
MiB = 1024 ** 2


class Partition:
    def __init__(self, name, size, fstype="ext4", mountpoint=None,
                 used=0, is_root=False):
        self.name = name            # e.g. "sda1"
        self.size = size            # bytes
        self.fstype = fstype
        self.mountpoint = mountpoint
        self.used = used            # simulated used bytes (non-root parts)
        self.is_root = is_root

    @property
    def dev(self):
        return f"/dev/{self.name}"

    def uuid(self):
        h = hashlib.md5(self.name.encode()).hexdigest()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class Disk:
    def __init__(self, name, size):
        self.name = name            # e.g. "sda"
        self.size = size
        self.partitions = []

    @property
    def dev(self):
        return f"/dev/{self.name}"


class DiskManager:
    def __init__(self, kernel):
        self.kernel = kernel
        self.disks = []
        self._build_default()

    def _build_default(self):
        sda = Disk("sda", 20 * GiB)
        sda.partitions = [
            Partition("sda1", 19 * GiB, "ext4", mountpoint="/", is_root=True),
            Partition("sda2", 1 * GiB, "swap", mountpoint=None),
        ]
        sdb = Disk("sdb", 8 * GiB)
        sdb.partitions = [
            Partition("sdb1", 8 * GiB, "ext4", mountpoint=None,
                      used=int(2.3 * GiB)),
        ]
        self.disks = [sda, sdb]

    # -- lookups ----------------------------------------------------------
    def all_partitions(self):
        return [p for d in self.disks for p in d.partitions]

    def partition_by_name(self, name):
        name = name.replace("/dev/", "")
        for p in self.all_partitions():
            if p.name == name:
                return p
        return None

    def mounted(self):
        return [p for p in self.all_partitions() if p.mountpoint]

    def mount_at(self, path):
        for p in self.all_partitions():
            if p.mountpoint == path:
                return p
        return None

    # -- used space -------------------------------------------------------
    def root_used_bytes(self):
        """Real bytes stored in the virtual filesystem (the root partition)."""
        def walk(node):
            total = node.size
            if node.is_dir:
                for c in node.children.values():
                    total += walk(c)
            return total
        return walk(self.kernel.fs.root)

    def used_bytes(self, part):
        if part.is_root:
            # baseline OS footprint + live filesystem contents
            return int(3.1 * GiB) + self.root_used_bytes()
        return part.used

    # -- operations -------------------------------------------------------
    def mount(self, dev, path):
        part = self.partition_by_name(dev)
        if not part:
            raise ValueError(f"special device {dev} does not exist")
        if part.mountpoint:
            raise ValueError(f"{dev} already mounted on {part.mountpoint}")
        if not self.kernel.fs.exists(path):
            raise ValueError(f"mount point {path} does not exist")
        part.mountpoint = path
        return part

    def umount(self, target):
        part = self.mount_at(target) or self.partition_by_name(target)
        if not part or not part.mountpoint:
            raise ValueError(f"{target}: not mounted")
        if part.is_root:
            raise ValueError("cannot unmount root filesystem")
        part.mountpoint = None
        return part

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {"mounts": {p.name: p.mountpoint for p in self.all_partitions()}}

    def load_dict(self, d):
        mounts = d.get("mounts", {})
        for p in self.all_partitions():
            if p.name in mounts:
                p.mountpoint = mounts[p.name]
