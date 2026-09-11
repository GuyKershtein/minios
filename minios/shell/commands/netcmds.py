"""Networking commands: ip, ifconfig, ping, ss, netstat."""

from __future__ import annotations

from .base import Command


class Ip(Command):
    name = "ip"
    synopsis = "ip addr | ip link | ip route"
    help_text = ("Show / manipulate networking.\n"
                 "  ip addr    show addresses\n  ip link    show interfaces\n"
                 "  ip route   show the routing table\n"
                 "  ip link set <dev> up|down")

    def run(self, ctx):
        args = ctx.argv[1:]
        net = ctx.kernel.net
        obj = args[0] if args else "addr"
        if obj in ("a", "addr", "address"):
            return self._addr(ctx, net)
        if obj in ("l", "link"):
            if len(args) >= 4 and args[1] == "set" and args[3] in ("up", "down"):
                if not self.require_root(ctx):
                    return 1
                try:
                    net.set_state(args[2], args[3].upper())
                except ValueError as e:
                    ctx.errorln(f"ip: {e}")
                    return 1
                return 0
            return self._link(ctx, net)
        if obj in ("r", "route"):
            return self._route(ctx, net)
        ctx.errorln(f"ip: unknown object \"{obj}\"")
        return 1

    def _addr(self, ctx, net):
        for i, iface in enumerate(net.interfaces.values(), 1):
            flags = "LOOPBACK" if iface.loopback else "BROADCAST,MULTICAST"
            ctx.writeln(f"{i}: {iface.name}: <{flags},{iface.state}> "
                        f"mtu {iface.mtu} state {iface.state}")
            ctx.writeln(f"    link/ether {iface.mac}")
            if iface.ipv4:
                ctx.writeln(f"    inet {iface.ipv4}/{iface.prefix} "
                            f"scope {'host' if iface.loopback else 'global'} "
                            f"{iface.name}")
        return 0

    def _link(self, ctx, net):
        for i, iface in enumerate(net.interfaces.values(), 1):
            ctx.writeln(f"{i}: {iface.name}: <{iface.state}> mtu {iface.mtu} "
                        f"state {iface.state}")
            ctx.writeln(f"    link/ether {iface.mac}")
        return 0

    def _route(self, ctx, net):
        for r in net.routes:
            if r.dest == "default":
                ctx.writeln(f"default via {r.gateway} dev {r.dev}")
            else:
                via = f" via {r.gateway}" if r.gateway else ""
                ctx.writeln(f"{r.cidr()}{via} dev {r.dev} scope {r.scope}")
        return 0


class Ifconfig(Command):
    name = "ifconfig"
    synopsis = "ifconfig [iface [up|down]]"
    help_text = "Configure or display network interfaces (classic style)."

    def run(self, ctx):
        net = ctx.kernel.net
        args = ctx.argv[1:]
        if len(args) >= 2 and args[1] in ("up", "down"):
            if not self.require_root(ctx):
                return 1
            try:
                net.set_state(args[0], args[1].upper())
            except ValueError as e:
                ctx.errorln(f"ifconfig: {e}")
                return 1
            return 0
        ifaces = ([net.get(args[0])] if args else net.interfaces.values())
        for iface in ifaces:
            if iface is None:
                ctx.errorln(f"{args[0]}: error fetching interface information")
                return 1
            ctx.writeln(f"{iface.name}: flags=<{iface.state}>  mtu {iface.mtu}")
            if iface.ipv4:
                ctx.writeln(f"        inet {iface.ipv4}  netmask {iface.netmask}")
            if not iface.loopback:
                ctx.writeln(f"        ether {iface.mac}")
            ctx.writeln(f"        RX packets {iface.rx_packets}  "
                        f"TX packets {iface.tx_packets}")
            ctx.writeln("")
        return 0


class Ping(Command):
    name = "ping"
    synopsis = "ping [-c count] host"
    help_text = "Send simulated ICMP echo requests to a host."

    def run(self, ctx):
        _, values, operands = self.parse_flags(ctx.argv[1:], valued=("c",))
        if not operands:
            ctx.errorln("ping: usage: ping [-c count] destination")
            return 1
        host = operands[0]
        count = int(values["c"]) if values.get("c", "").isdigit() else 4
        r = ctx.kernel.net.ping(host, count)
        if "error" in r:
            ctx.errorln(r["error"])
            return 2
        ip = r["ip"]
        ctx.writeln(f"PING {host} ({ip}) 56(84) bytes of data.")
        total = 0.0
        times = []
        for rep in r["replies"]:
            t = rep["time"]
            times.append(t)
            total += t
            ctx.writeln(f"64 bytes from {ip}: icmp_seq={rep['seq']} "
                        f"ttl={rep['ttl']} time={t} ms")
        loss = int(100 * (r["transmitted"] - r["received"]) / r["transmitted"])
        ctx.writeln("")
        ctx.writeln(f"--- {host} ping statistics ---")
        ctx.writeln(f"{r['transmitted']} packets transmitted, "
                    f"{r['received']} received, {loss}% packet loss")
        if times:
            ctx.writeln(f"rtt min/avg/max = {min(times)}/"
                        f"{round(total / len(times), 3)}/{max(times)} ms")
        return 0


class Ss(Command):
    name = "ss"
    aliases = ("netstat",)
    synopsis = "ss [-t] [-u] [-l] [-n]"
    help_text = ("Show socket statistics.\n"
                 "  -t tcp   -u udp   -l listening only   -n numeric")

    def run(self, ctx):
        flags, _, _ = self.parse_flags(ctx.argv[1:])
        want_tcp = "t" in flags
        want_udp = "u" in flags
        listening = "l" in flags
        if not (want_tcp or want_udp):
            want_tcp = want_udp = True

        socks = ctx.kernel.net.sockets
        ctx.writeln(f"{'Netid':<6}{'State':<10}{'Local Address:Port':<24}"
                    f"{'Peer Address:Port':<20}Process")
        for s in socks:
            if s.proto == "tcp" and not want_tcp:
                continue
            if s.proto == "udp" and not want_udp:
                continue
            if listening and s.state not in ("LISTEN", "UNCONN"):
                continue
            proc = f'users:(("{s.program}",pid={s.pid}))' if s.program else ""
            ctx.writeln(f"{s.proto:<6}{s.state:<10}{s.local:<24}"
                        f"{s.peer:<20}{proc}")
        return 0
