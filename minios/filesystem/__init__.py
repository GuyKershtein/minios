"""Virtual filesystem subsystem."""

from .filesystem import FileSystem, FSError
from .inode import Inode
from . import permissions

__all__ = ["FileSystem", "FSError", "Inode", "permissions"]
