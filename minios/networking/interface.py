"""Network interfaces."""

from __future__ import annotations


class Interface:
    def __init__(self, name, ipv4=None, prefix=24, mac=None, state="UP",
                 mtu=1500, loopback=False):
        self.name = name
        self.ipv4 = ipv4            # e.g. "192.168.1.10"
        self.prefix = prefix        # netmask length
        self.mac = mac
        self.state = state          # "UP" / "DOWN"
        self.mtu = mtu
        self.loopback = loopback
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.rx_packets = 0
        self.tx_packets = 0

    @property
    def netmask(self):
        bits = (0xFFFFFFFF << (32 - self.prefix)) & 0xFFFFFFFF
        return ".".join(str((bits >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))

    @property
    def network(self):
        if not self.ipv4:
            return None
        ip = _ip_to_int(self.ipv4)
        mask = (0xFFFFFFFF << (32 - self.prefix)) & 0xFFFFFFFF
        return _int_to_ip(ip & mask)

    def in_subnet(self, ip):
        if not self.ipv4:
            return False
        mask = (0xFFFFFFFF << (32 - self.prefix)) & 0xFFFFFFFF
        return (_ip_to_int(ip) & mask) == (_ip_to_int(self.ipv4) & mask)

    def to_dict(self):
        return {"name": self.name, "ipv4": self.ipv4, "prefix": self.prefix,
                "mac": self.mac, "state": self.state, "mtu": self.mtu,
                "loopback": self.loopback}

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], d["ipv4"], d["prefix"], d["mac"], d["state"],
                   d["mtu"], d["loopback"])


def _ip_to_int(ip):
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def _int_to_ip(n):
    return ".".join(str((n >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))
