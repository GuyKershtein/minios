"""Service management and logging commands: systemctl, service, journalctl,
dmesg, logger."""

from __future__ import annotations

import time

from ...filesystem import FSError
from ...services.manager import ServiceError
from .base import Command


class Systemctl(Command):
    name = "systemctl"
    synopsis = "systemctl start|stop|restart|status|enable|disable|list-units [unit]"
    help_text = ("Control the service manager.\n"
                 "  systemctl status <svc>   show service status\n"
                 "  systemctl start|stop|restart <svc>\n"
                 "  systemctl enable|disable <svc>\n"
                 "  systemctl is-active|is-enabled <svc>\n"
                 "  systemctl list-units     list all services")

    _MUTATING = {"start", "stop", "restart", "enable", "disable"}

    def run(self, ctx):
        args = ctx.argv[1:]
        sm = ctx.kernel.services
        if not args or args[0] in ("list-units", "list-unit-files"):
            return self._list(ctx, sm)
        action = args[0]
        if len(args) < 2:
            ctx.errorln(f"systemctl: {action}: unit name required")
            return 1
        unit = args[1]
        if action in self._MUTATING and not self.require_root(ctx):
            return 1
        try:
            if action == "status":
                return self._status(ctx, sm, unit)
            if action == "is-active":
                svc = sm._require(unit)
                ctx.writeln("active" if svc.active else "inactive")
                return 0 if svc.active else 3
            if action == "is-enabled":
                svc = sm._require(unit)
                ctx.writeln("enabled" if svc.enabled else "disabled")
                return 0 if svc.enabled else 1
            if action == "start":
                sm.start(unit)
            elif action == "stop":
                sm.stop(unit)
            elif action == "restart":
                sm.restart(unit)
            elif action == "enable":
                sm.enable(unit)
                ctx.writeln(f"Created symlink /etc/systemd/system/"
                            f"multi-user.target.wants/{unit}.service.")
            elif action == "disable":
                sm.disable(unit)
                ctx.writeln(f"Removed /etc/systemd/system/"
                            f"multi-user.target.wants/{unit}.service.")
            else:
                ctx.errorln(f"systemctl: unknown command '{action}'")
                return 1
        except ServiceError as e:
            ctx.errorln(str(e))
            return 1
        return 0

    def _status(self, ctx, sm, unit):
        svc = sm.get(unit)
        if svc is None:
            ctx.errorln(f"Unit {unit}.service could not be found.")
            return 4
        dot = "●"
        loaded = "enabled" if svc.enabled else "disabled"
        if svc.active:
            since = time.strftime("%a %Y-%m-%d %H:%M:%S",
                                  time.localtime(svc.since or time.time()))
            active = f"active ({svc.sub}) since {since}"
        else:
            active = "inactive (dead)"
        ctx.writeln(f"{dot} {svc.unit} - {svc.description}")
        ctx.writeln(f"     Loaded: loaded (/lib/systemd/system/{svc.unit}; "
                    f"{loaded})")
        ctx.writeln(f"     Active: {active}")
        if svc.main_pid:
            ctx.writeln(f"   Main PID: {svc.main_pid} ({svc.proc})")
        return 0 if svc.active else 3

    def _list(self, ctx, sm):
        ctx.writeln(f"{'UNIT':<22}{'LOAD':<8}{'ACTIVE':<10}{'SUB':<10}"
                    f"DESCRIPTION")
        for svc in sm.services.values():
            ctx.writeln(f"{svc.unit:<22}{'loaded':<8}"
                        f"{('active' if svc.active else 'inactive'):<10}"
                        f"{svc.sub:<10}{svc.description}")
        return 0


class ServiceCmd(Command):
    name = "service"
    synopsis = "service <name> start|stop|restart|status"
    help_text = "SysV-style wrapper around systemctl."

    def run(self, ctx):
        if len(ctx.argv) < 3:
            ctx.errorln("service: usage: service <name> <action>")
            return 1
        name, action = ctx.argv[1], ctx.argv[2]
        # delegate to systemctl by rewriting argv
        ctx.argv = ["systemctl", action, name]
        return ctx.shell.registry["systemctl"].run(ctx)


class Journalctl(Command):
    name = "journalctl"
    synopsis = "journalctl [-u unit] [-n N]"
    help_text = "Query the system log (/var/log/syslog)."

    def run(self, ctx):
        _, values, _ = self.parse_flags(ctx.argv[1:], valued=("u", "n"))
        try:
            data = ctx.kernel.sys_open_read("/var/log/syslog")
        except FSError:
            data = ""
        lines = data.splitlines()
        if "u" in values:
            lines = [ln for ln in lines if values["u"] in ln]
        if values.get("n", "").isdigit():
            lines = lines[-int(values["n"]):]
        ctx.writeln("-- Logs begin --")
        for ln in lines:
            ctx.writeln(ln)
        return 0


class Dmesg(Command):
    name = "dmesg"
    synopsis = "dmesg"
    help_text = "Print the kernel ring buffer (/var/log/kernel.log)."

    def run(self, ctx):
        try:
            data = ctx.kernel.sys_open_read("/var/log/kernel.log")
        except FSError:
            data = ""
        ctx.write(data)
        if data and not data.endswith("\n"):
            ctx.write("\n")
        return 0


class Logger(Command):
    name = "logger"
    synopsis = "logger [-t tag] message"
    help_text = "Write a message to the system log."

    def run(self, ctx):
        _, values, operands = self.parse_flags(ctx.argv[1:], valued=("t",))
        tag = values.get("t", ctx.session.username)
        msg = " ".join(operands)
        ctx.kernel.log("syslog", f"{tag}: {msg}")
        return 0
