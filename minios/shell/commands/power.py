"""Power management: shutdown, reboot, poweroff, halt, sync."""

from __future__ import annotations

from .base import Command


class _PowerBase(Command):
    def _go(self, ctx, reboot):
        if not self.require_root(ctx):
            return 1
        ctx.kernel.log("syslog", "System is going down for "
                       + ("reboot" if reboot else "power-off") + " NOW!")
        try:
            ctx.kernel.save()
        except Exception:
            pass
        ctx.shell.request_exit = True
        ctx.kernel.reboot_requested = reboot
        ctx.writeln("The system is going down now...")
        return 0


class Shutdown(_PowerBase):
    name = "shutdown"
    synopsis = "shutdown [-r] [now]"
    help_text = "Shut down (or with -r, reboot) the system (root only)."

    def run(self, ctx):
        reboot = "-r" in ctx.argv[1:]
        return self._go(ctx, reboot)


class Reboot(_PowerBase):
    name = "reboot"
    synopsis = "reboot"
    help_text = "Reboot the system (root only)."

    def run(self, ctx):
        return self._go(ctx, True)


class Poweroff(_PowerBase):
    name = "poweroff"
    aliases = ("halt",)
    synopsis = "poweroff"
    help_text = "Power off the system (root only)."

    def run(self, ctx):
        return self._go(ctx, False)


class Sync(Command):
    name = "sync"
    synopsis = "sync"
    help_text = "Flush the current system state to persistent storage."

    def run(self, ctx):
        ok = False
        try:
            ok = ctx.kernel.save()
        except Exception as e:
            ctx.errorln(f"sync: {e}")
            return 1
        if not ok:
            ctx.errorln("sync: persistence is disabled (no state file)")
            return 1
        return 0
