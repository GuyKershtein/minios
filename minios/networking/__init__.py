"""Simulated networking: interfaces, routing and sockets."""

from .manager import NetworkManager
from .interface import Interface
from .routing import Route
from .sockets import Socket

__all__ = ["NetworkManager", "Interface", "Route", "Socket"]
