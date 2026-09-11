"""System services (systemd-style) and their manager."""

from .service import Service
from .manager import ServiceManager

__all__ = ["Service", "ServiceManager"]
