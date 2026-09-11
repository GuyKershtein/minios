from conftest import run


# -- interfaces ------------------------------------------------------------
def test_default_interfaces(kernel):
    assert "lo" in kernel.net.interfaces
    assert "eth0" in kernel.net.interfaces
    assert kernel.net.interfaces["eth0"].ipv4 == "192.168.1.10"


def test_ip_addr(shell):
    out, _ = run(shell, "ip addr")
    assert "eth0" in out and "192.168.1.10/24" in out
    assert "lo" in out and "127.0.0.1/8" in out


def test_ip_route(shell):
    out, _ = run(shell, "ip route")
    assert "default via 192.168.1.1" in out


def test_ifconfig(shell):
    out, _ = run(shell, "ifconfig")
    assert "eth0" in out and "192.168.1.10" in out
    assert "netmask 255.255.255.0" in out


def test_interface_down_requires_root(shell):
    out, code = run(shell, "ip link set eth0 down")
    assert code == 1
    assert "permission denied" in out.lower()
    assert shell.kernel.net.interfaces["eth0"].state == "UP"


def test_interface_down_as_root(shell):
    shell.kernel.session.uid = 0
    out, code = run(shell, "ip link set eth0 down")
    assert code == 0
    assert shell.kernel.net.interfaces["eth0"].state == "DOWN"


# -- name resolution / ping ------------------------------------------------
def test_resolve_hosts(kernel):
    assert kernel.net.resolve("localhost") == "127.0.0.1"
    assert kernel.net.resolve("8.8.8.8") == "8.8.8.8"
    assert kernel.net.resolve("gateway") == "192.168.1.1"
    assert kernel.net.resolve("no-such-host") is None


def test_ping_localhost(shell):
    out, code = run(shell, "ping -c 2 localhost")
    assert code == 0
    assert "PING localhost (127.0.0.1)" in out
    assert "2 packets transmitted, 2 received" in out


def test_ping_unknown_host(shell):
    out, code = run(shell, "ping -c 1 does-not-exist")
    assert code != 0
    assert "Name or service not known" in out


def test_ping_unreachable_when_iface_down(shell):
    shell.kernel.net.interfaces["eth0"].state = "DOWN"
    out, code = run(shell, "ping -c 1 8.8.8.8")
    assert code != 0
    assert "unreachable" in out.lower()


# -- sockets ---------------------------------------------------------------
def test_ss_lists_sockets(shell):
    out, _ = run(shell, "ss -tuln")
    assert "sshd" in out
    assert ":22" in out


def test_listen_registration(kernel):
    kernel.net.listen("tcp", 8080, "myserver", pid=999)
    ports = [(s.local_port, s.program) for s in kernel.net.sockets]
    assert (8080, "myserver") in ports


def test_persistence_of_network(tmp_path):
    from minios.kernel import Kernel
    statefile = str(tmp_path / "state.json")
    k1 = Kernel(statefile=statefile)
    k1.net.interfaces["eth0"].state = "DOWN"
    k1.net.listen("tcp", 9999, "persisted-srv")
    k1.save()

    k2 = Kernel(statefile=statefile)
    k2.load()
    assert k2.net.interfaces["eth0"].state == "DOWN"
    assert any(s.local_port == 9999 for s in k2.net.sockets)
