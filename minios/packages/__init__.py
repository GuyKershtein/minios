"""Package management subsystem (apt-like)."""

from .repository import Repository, Package
from .package_manager import PackageManager

__all__ = ["Repository", "Package", "PackageManager"]
