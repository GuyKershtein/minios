"""Routing table entries."""

from __future__ import annotations


class Route:
    def __init__(self, dest, dev, gateway=None, prefix=None, metric=0,
                 scope="global"):
        self.dest = dest          # "default" or a network like "192.168.1.0"
        self.dev = dev
        self.gateway = gateway
        self.prefix = prefix
        self.metric = metric
        self.scope = scope

    def cidr(self):
        if self.dest == "default":
            return "default"
        return f"{self.dest}/{self.prefix}"

    def to_dict(self):
        return {"dest": self.dest, "dev": self.dev, "gateway": self.gateway,
                "prefix": self.prefix, "metric": self.metric,
                "scope": self.scope}

    @classmethod
    def from_dict(cls, d):
        return cls(d["dest"], d["dev"], d["gateway"], d["prefix"],
                   d["metric"], d["scope"])
