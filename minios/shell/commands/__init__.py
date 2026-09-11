"""Command registry.

Commands register themselves by subclassing :class:`Command` and being listed
in :func:`build_registry`. The shell looks commands up by name here.
"""

from __future__ import annotations

from .base import Command, ExecutionContext


def build_registry():
    from . import coreutils      # noqa: F401  (registers commands)
    from . import usermgmt       # noqa: F401
    from . import proccmds       # noqa: F401
    from . import sysinfo        # noqa: F401
    from . import netcmds        # noqa: F401
    from . import pkgcmds        # noqa: F401
    from . import servicecmds    # noqa: F401
    from . import scriptcmds     # noqa: F401
    from . import moreutils      # noqa: F401
    from . import editor         # noqa: F401
    from . import power          # noqa: F401
    registry = {}

    def walk(cls):
        for sub in cls.__subclasses__():
            walk(sub)
            if getattr(sub, "name", "?") == "?":
                continue  # abstract intermediate base (e.g. _PowerBase)
            inst = sub()
            for name in [inst.name, *inst.aliases]:
                registry[name] = inst

    walk(Command)
    return registry


__all__ = ["Command", "ExecutionContext", "build_registry"]
