"""The network manager ties interfaces, routes and sockets together and
simulates name resolution and ICMP ping."""

from __future__ import annotations

import random

from .interface import Interface, _ip_to_int
from .routing import Route
from .sockets import Socket


class NetworkManager:
    def __init__(self, kernel):
        self.kernel = kernel
        self.interfaces = {}
        self.routes = []
        self.sockets = []
        self._build_default()

    def _build_default(self):
        lo = Interface("lo", "127.0.0.1", prefix=8, mac="00:00:00:00:00:00",
                       state="UP", mtu=65536, loopback=True)
        eth0 = Interface("eth0", "192.168.1.10", prefix=24,
                         mac="52:54:00:12:34:56", state="UP", mtu=1500)
        self.interfaces = {"lo": lo, "eth0": eth0}
        self.routes = [
            Route("default", "eth0", gateway="192.168.1.1"),
            Route("192.168.1.0", "eth0", prefix=24, scope="link"),
            Route("127.0.0.0", "lo", prefix=8, scope="host"),
        ]
        # baseline listening socket (sshd's socket is opened by its service)
        self.sockets = [
            Socket("udp", "127.0.0.53", 53, "UNCONN", program="systemd-resolve"),
        ]

    # -- interfaces -------------------------------------------------------
    def get(self, name):
        return self.interfaces.get(name)

    def set_state(self, name, state):
        iface = self.interfaces.get(name)
        if not iface:
            raise ValueError(f"Cannot find device \"{name}\"")
        iface.state = state
        return iface

    def primary_ip(self):
        eth = self.interfaces.get("eth0")
        return eth.ipv4 if eth and eth.state == "UP" else "127.0.0.1"

    # -- sockets ----------------------------------------------------------
    def listen(self, proto, port, program, pid=None, ip="0.0.0.0"):
        self.sockets.append(Socket(proto, ip, port, "LISTEN", program=program,
                                   pid=pid))

    def close_program(self, program):
        self.sockets = [s for s in self.sockets if s.program != program]

    # -- name resolution --------------------------------------------------
    def resolve(self, host):
        """Resolve a hostname to an IP using /etc/hosts, our own name and
        interfaces. Bare IPv4 addresses resolve to themselves."""
        if _is_ipv4(host):
            return host
        # /etc/hosts
        try:
            data = self.kernel.sys_open_read("/etc/hosts")
            for line in data.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                ip, names = parts[0], parts[1:]
                if host in names:
                    return ip
        except Exception:
            pass
        if host in (self.kernel.HOSTNAME, "localhost"):
            return "127.0.0.1"
        return None

    # -- ping -------------------------------------------------------------
    def ping(self, host, count=4):
        ip = self.resolve(host)
        results = {"host": host, "ip": ip, "replies": [], "transmitted": count,
                   "received": 0, "reachable": False}
        if ip is None:
            results["error"] = f"ping: {host}: Name or service not known"
            return results
        eth_up = self.interfaces.get("eth0") and \
            self.interfaces["eth0"].state == "UP"
        loop = ip.startswith("127.")
        # reachable if loopback, or eth0 is up (for LAN and simulated internet)
        if not (loop or eth_up):
            results["error"] = "connect: Network is unreachable"
            return results
        results["reachable"] = True
        for seq in range(1, count + 1):
            if loop:
                rtt = round(random.uniform(0.015, 0.05), 3)
            elif self.interfaces["eth0"].in_subnet(ip):
                rtt = round(random.uniform(0.2, 1.5), 3)
            else:
                rtt = round(random.uniform(8.0, 30.0), 3)
            results["replies"].append({"seq": seq, "ttl": 64, "time": rtt})
            results["received"] += 1
        return results

    # -- serialization ----------------------------------------------------
    def to_dict(self):
        return {
            "interfaces": {n: i.to_dict() for n, i in self.interfaces.items()},
            "routes": [r.to_dict() for r in self.routes],
            "sockets": [s.to_dict() for s in self.sockets],
        }

    def load_dict(self, d):
        if "interfaces" in d:
            self.interfaces = {n: Interface.from_dict(v)
                               for n, v in d["interfaces"].items()}
        if "routes" in d:
            self.routes = [Route.from_dict(r) for r in d["routes"]]
        if "sockets" in d:
            self.sockets = [Socket.from_dict(s) for s in d["sockets"]]


def _is_ipv4(s):
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False
