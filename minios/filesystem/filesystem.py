"""The virtual filesystem: path resolution and tree operations.

The FileSystem owns the root inode and knows how to walk paths. It is
permission-aware: every mutating/reading operation takes a ``cred`` (an object
exposing ``uid`` and ``gids``) so access can be enforced. The Kernel is the
usual caller and passes the current session's credentials.
"""

from __future__ import annotations

from . import permissions as perm
from .inode import Inode


class FSError(Exception):
    """A filesystem error carrying a Unix-style message."""


class _Cred:
    """Minimal credentials holder used for internal/bootstrap operations."""

    def __init__(self, uid=0, gids=(0,)):
        self.uid = uid
        self.gids = tuple(gids)


ROOT_CRED = _Cred(0, (0,))

# Directories created for a fresh install (Filesystem Hierarchy Standard subset)
_DEFAULT_TREE = [
    "/bin", "/boot", "/dev", "/etc", "/home", "/home/user",
    "/lib", "/media", "/mnt", "/opt", "/proc", "/root", "/run",
    "/sbin", "/srv", "/sys", "/tmp",
    "/usr", "/usr/bin", "/usr/lib", "/usr/local", "/usr/local/bin",
    "/var", "/var/log", "/var/cache", "/var/lib",
]


class FileSystem:
    def __init__(self, build_default=True):
        self.root = Inode(ftype="dir", mode=0o755, uid=0, gid=0, name="/")
        if build_default:
            self._build_default_tree()

    # -- default install --------------------------------------------------
    def _build_default_tree(self):
        for path in _DEFAULT_TREE:
            self.mkdir(path, ROOT_CRED, mode=0o755, parents=True,
                       exist_ok=True)
        # /tmp is world-writable, /home/user owned by the user account
        self.chmod("/tmp", ROOT_CRED, 0o1777)
        self.chmod("/root", ROOT_CRED, 0o700)
        self.chown("/home/user", ROOT_CRED, uid=1000, gid=1000)
        self.chmod("/home/user", ROOT_CRED, 0o755)

    # -- path handling ----------------------------------------------------
    @staticmethod
    def split(path):
        return [p for p in path.split("/") if p not in ("", ".")]

    def _walk(self, path, cwd, cred, follow_final=True):
        """Resolve ``path`` to an inode. ``cwd`` is used for relative paths.

        Symlinks in intermediate components are always followed; the final
        component is followed only if ``follow_final`` is True.
        """
        if path.startswith("/"):
            node = self.root
        else:
            node = self._resolve_cwd(cwd)
        parts = self.split(path)
        for i, part in enumerate(parts):
            is_final = i == len(parts) - 1
            if part == "..":
                node = node.parent or node
                continue
            if not node.is_dir:
                raise FSError(f"not a directory: {part}")
            if not perm.can(node, perm.X, cred.uid, cred.gids):
                raise FSError(f"permission denied: {path}")
            child = node.children.get(part)
            if child is None:
                raise FSError(f"no such file or directory: {path}")
            if child.is_link and (not is_final or follow_final):
                child = self._follow_link(child, cred, depth=0)
            node = child
        return node

    def _follow_link(self, link, cred, depth):
        if depth > 40:
            raise FSError("too many levels of symbolic links")
        target = link.target
        base = link.parent
        base_path = self.path_of(base)
        node = self._walk(target, base_path, cred, follow_final=True)
        return node

    def _resolve_cwd(self, cwd):
        if isinstance(cwd, Inode):
            return cwd
        return self._walk(cwd or "/", "/", ROOT_CRED)

    def resolve(self, path, cwd="/", cred=ROOT_CRED, follow=True):
        return self._walk(path, cwd, cred, follow_final=follow)

    def exists(self, path, cwd="/", cred=ROOT_CRED):
        try:
            self._walk(path, cwd, cred, follow_final=True)
            return True
        except FSError:
            return False

    def path_of(self, node):
        """Absolute path of an inode by walking parents."""
        if node is self.root:
            return "/"
        parts = []
        cur = node
        while cur is not None and cur is not self.root:
            parts.append(cur.name)
            cur = cur.parent
        return "/" + "/".join(reversed(parts))

    def _parent_and_name(self, path, cwd, cred):
        parts = self.split(path)
        if not parts:
            raise FSError(f"invalid path: {path}")
        name = parts[-1]
        parent_path = "/".join(parts[:-1])
        if path.startswith("/"):
            parent_path = "/" + parent_path
        elif not parent_path:
            parent_path = "."
        parent = self._walk(parent_path or "/", cwd, cred, follow_final=True)
        return parent, name

    # -- operations -------------------------------------------------------
    def mkdir(self, path, cred, mode=0o755, parents=False, exist_ok=False,
              cwd="/"):
        if parents:
            node = self.root if path.startswith("/") else self._resolve_cwd(cwd)
            built = ""
            for part in self.split(path):
                built = built + "/" + part
                if part in node.children:
                    node = node.children[part]
                    if node.is_link:
                        node = self._follow_link(node, cred, 0)
                    continue
                if not perm.can(node, perm.W, cred.uid, cred.gids):
                    raise FSError(f"permission denied: {built}")
                child = Inode("dir", mode, cred.uid, cred.gids[0], part, node)
                node.children[part] = child
                node.touch()
                node = child
            return node

        parent, name = self._parent_and_name(path, cwd, cred)
        if name in parent.children:
            if exist_ok:
                return parent.children[name]
            raise FSError(f"cannot create directory '{path}': File exists")
        if not perm.can(parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        child = Inode("dir", mode, cred.uid, cred.gids[0], name, parent)
        parent.children[name] = child
        parent.touch()
        return child

    def create(self, path, cwd, cred, mode=0o644, exist_ok=True):
        """Create (or update mtime of) a regular file."""
        parent, name = self._parent_and_name(path, cwd, cred)
        if name in parent.children:
            node = parent.children[name]
            if not exist_ok:
                raise FSError(f"cannot create '{path}': File exists")
            node.touch(atime=True)
            return node
        if not perm.can(parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        node = Inode("file", mode, cred.uid, cred.gids[0], name, parent)
        parent.children[name] = node
        parent.touch()
        return node

    def mknod(self, path, cred, ftype="char", mode=0o666, cwd="/"):
        """Create a device node (ftype 'char' or 'block')."""
        parent, name = self._parent_and_name(path, cwd, cred)
        if name in parent.children:
            return parent.children[name]
        if not perm.can(parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        node = Inode(ftype, mode, cred.uid, cred.gids[0], name, parent)
        parent.children[name] = node
        parent.touch()
        return node

    def symlink(self, target, linkpath, cwd, cred):
        parent, name = self._parent_and_name(linkpath, cwd, cred)
        if name in parent.children:
            raise FSError(f"cannot create symlink '{linkpath}': File exists")
        if not perm.can(parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {linkpath}")
        node = Inode("link", 0o777, cred.uid, cred.gids[0], name, parent)
        node.target = target
        parent.children[name] = node
        parent.touch()
        return node

    def read(self, path, cwd, cred):
        node = self._walk(path, cwd, cred, follow_final=True)
        if node.is_dir:
            raise FSError(f"{path}: Is a directory")
        if not perm.can(node, perm.R, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        node.atime = node.atime  # read updates atime in real Linux; keep simple
        return node.content

    def write(self, path, cwd, cred, data, append=False, create=True,
              mode=0o644):
        try:
            node = self._walk(path, cwd, cred, follow_final=True)
        except FSError:
            if not create:
                raise
            node = self.create(path, cwd, cred, mode=mode)
        if node.is_dir:
            raise FSError(f"{path}: Is a directory")
        if not perm.can(node, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        node.content = (node.content + data) if append else data
        node.touch()
        return node

    def listdir(self, path, cwd, cred):
        node = self._walk(path, cwd, cred, follow_final=True)
        if not node.is_dir:
            return [(node.name, node)]
        if not perm.can(node, perm.R, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        return sorted(node.children.items())

    def remove(self, path, cwd, cred, recursive=False):
        parent, name = self._parent_and_name(path, cwd, cred)
        node = parent.children.get(name)
        if node is None:
            raise FSError(f"cannot remove '{path}': No such file or directory")
        if node.is_dir and node.children and not recursive:
            raise FSError(f"cannot remove '{path}': Directory not empty")
        if not perm.can(parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {path}")
        del parent.children[name]
        parent.touch()

    def rmdir(self, path, cwd, cred):
        node = self._walk(path, cwd, cred, follow_final=True)
        if not node.is_dir:
            raise FSError(f"failed to remove '{path}': Not a directory")
        if node.children:
            raise FSError(f"failed to remove '{path}': Directory not empty")
        self.remove(path, cwd, cred)

    def move(self, src, dst, cwd, cred):
        s_parent, s_name = self._parent_and_name(src, cwd, cred)
        node = s_parent.children.get(s_name)
        if node is None:
            raise FSError(f"cannot stat '{src}': No such file or directory")
        # If dst is an existing directory, move into it
        try:
            d_node = self._walk(dst, cwd, cred, follow_final=True)
            if d_node.is_dir:
                d_parent, d_name = d_node, s_name
            else:
                d_parent, d_name = self._parent_and_name(dst, cwd, cred)
        except FSError:
            d_parent, d_name = self._parent_and_name(dst, cwd, cred)
        if not perm.can(d_parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {dst}")
        del s_parent.children[s_name]
        node.name = d_name
        node.parent = d_parent
        d_parent.children[d_name] = node
        s_parent.touch()
        d_parent.touch()

    def copy(self, src, dst, cwd, cred, recursive=False):
        node = self._walk(src, cwd, cred, follow_final=True)
        if node.is_dir and not recursive:
            raise FSError(f"-r not specified; omitting directory '{src}'")
        try:
            d_node = self._walk(dst, cwd, cred, follow_final=True)
            if d_node.is_dir:
                d_parent, d_name = d_node, node.name
            else:
                d_parent, d_name = self._parent_and_name(dst, cwd, cred)
        except FSError:
            d_parent, d_name = self._parent_and_name(dst, cwd, cred)
        if not perm.can(d_parent, perm.W, cred.uid, cred.gids):
            raise FSError(f"permission denied: {dst}")
        clone = self._clone(node, d_name, d_parent, cred)
        d_parent.children[d_name] = clone
        d_parent.touch()

    def _clone(self, node, name, parent, cred):
        new = Inode(node.ftype, node.mode, cred.uid, cred.gids[0], name, parent)
        new.content = node.content
        new.target = node.target
        if node.is_dir:
            for cn, cc in node.children.items():
                new.children[cn] = self._clone(cc, cn, new, cred)
        return new

    def chmod(self, path, cred, mode, cwd="/"):
        node = self._walk(path, cwd, cred, follow_final=True)
        if cred.uid != 0 and cred.uid != node.uid:
            raise FSError(f"changing permissions of '{path}': Operation not permitted")
        node.mode = mode & 0o7777
        node.ctime = node.mtime
        return node

    def chown(self, path, cred, uid=None, gid=None, cwd="/"):
        node = self._walk(path, cwd, cred, follow_final=True)
        if cred.uid != 0:
            raise FSError(f"changing ownership of '{path}': Operation not permitted")
        if uid is not None:
            node.uid = uid
        if gid is not None:
            node.gid = gid
        node.ctime = node.mtime
        return node

    def stat(self, path, cwd, cred, follow=True):
        return self._walk(path, cwd, cred, follow_final=follow)

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {"root": self.root.to_dict()}

    @classmethod
    def from_dict(cls, d):
        fs = cls(build_default=False)
        fs.root = Inode.from_dict(d["root"], parent=None)
        fs.root.name = "/"
        return fs
