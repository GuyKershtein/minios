"""The service manager (a small systemd).

Services actually affect the running system: starting ``sshd`` spawns an sshd
process and opens a listening socket on port 22; stopping it kills the process
and closes the socket. Starting ``networking`` brings eth0 up. State changes
are logged to /var/log/syslog.
"""

from __future__ import annotations

import time

from .service import Service


class ServiceError(Exception):
    pass


def _default_services():
    return {
        "sshd": Service("sshd", "OpenSSH server daemon", proc="sshd",
                        port=22, proto="tcp", enabled=True),
        "cron": Service("cron", "Regular background program processing daemon",
                        proc="cron", enabled=True),
        "rsyslog": Service("rsyslog", "System Logging Service",
                           proc="rsyslogd", enabled=True),
        "networking": Service("networking", "Raise network interfaces",
                              brings_up_iface=True, oneshot=True, enabled=True),
        "getty": Service("getty", "Getty on tty1", proc="agetty",
                         enabled=False),
    }


class ServiceManager:
    def __init__(self, kernel):
        self.kernel = kernel
        self.services = _default_services()

    def get(self, name):
        return self.services.get(name.replace(".service", ""))

    # -- boot -------------------------------------------------------------
    def start_enabled(self):
        for svc in self.services.values():
            if svc.enabled:
                self._do_start(svc)

    # -- operations -------------------------------------------------------
    def start(self, name):
        svc = self._require(name)
        if svc.active:
            return svc
        self._do_start(svc)
        return svc

    def _do_start(self, svc):
        if svc.active:
            return
        if svc.proc:
            p = self.kernel.procmgr.spawn(svc.proc, [svc.proc], uid=0, ppid=1,
                                          state="S", mem_kb=5120)
            svc.main_pid = p.pid
        if svc.port:
            self.kernel.net.listen(svc.proto, svc.port, svc.proc or svc.name,
                                   pid=svc.main_pid)
        if svc.brings_up_iface:
            try:
                self.kernel.net.set_state("eth0", "UP")
            except ValueError:
                pass
        svc.active = True
        svc.since = time.time()
        self.kernel.log("syslog", f"Started {svc.description}.")

    def stop(self, name):
        svc = self._require(name)
        if not svc.active:
            return svc
        if svc.main_pid is not None:
            try:
                self.kernel.procmgr.exit(svc.main_pid)
            except Exception:
                pass
        if svc.port:
            self.kernel.net.close_program(svc.proc or svc.name)
        svc.active = False
        svc.main_pid = None
        self.kernel.log("syslog", f"Stopped {svc.description}.")
        return svc

    def restart(self, name):
        self.stop(name)
        return self.start(name)

    def enable(self, name):
        svc = self._require(name)
        svc.enabled = True
        self.kernel.log("syslog", f"Enabled {svc.unit}.")
        return svc

    def disable(self, name):
        svc = self._require(name)
        svc.enabled = False
        self.kernel.log("syslog", f"Disabled {svc.unit}.")
        return svc

    def _require(self, name):
        svc = self.get(name)
        if svc is None:
            raise ServiceError(f"Unit {name}.service could not be found.")
        return svc

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {name: svc.to_dict() for name, svc in self.services.items()}

    def load_dict(self, d):
        for name, sd in d.items():
            if name in self.services:
                self.services[name].load_dict(sd)
