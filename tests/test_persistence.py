"""Phase 9: comprehensive persistence across every subsystem."""

from conftest import run

from minios.kernel import Kernel


def test_full_state_roundtrip(tmp_path):
    statefile = str(tmp_path / "state.json")

    # --- first boot: change something in every subsystem ---
    k1 = Kernel(statefile=statefile)
    s1 = __import__("minios.shell", fromlist=["Shell"]).Shell(k1)
    k1.session = k1.make_session("root")

    run(s1, "mkdir /root/project")                         # filesystem
    run(s1, "echo persistent > /root/project/file.txt")
    run(s1, "useradd -m tester")                            # users
    run(s1, "passwd tester secretpw")
    run(s1, "apt install cowsay")                           # packages
    run(s1, "systemctl disable cron")                       # services
    run(s1, "ip link set eth0 down")                        # networking
    daemon = k1.procmgr.spawn("mydaemon", ["mydaemon"], state="R")  # processes
    run(s1, "export MYVAR=hello")                           # environment
    assert k1.save()

    # --- reboot: brand new kernel from the same state file ---
    k2 = Kernel(statefile=statefile)
    assert k2.load()
    s2 = __import__("minios.shell", fromlist=["Shell"]).Shell(k2)

    # filesystem
    out, _ = run(s2, "cat /root/project/file.txt")
    assert out == "persistent\n"
    # users + auth
    assert k2.userdb.get_user("tester") is not None
    assert k2.authenticate("tester", "secretpw")
    # packages
    assert k2.pkg.is_installed("cowsay")
    assert k2.fs.exists("/usr/bin/cowsay")
    # services
    assert not k2.services.get("cron").enabled
    # networking
    assert k2.net.interfaces["eth0"].state == "DOWN"
    # processes
    assert k2.procmgr.get(daemon.pid) is not None
    # environment
    assert k2.session.env.get("MYVAR") == "hello"


def test_save_is_atomic(tmp_path):
    import os
    statefile = str(tmp_path / "state.json")
    k = Kernel(statefile=statefile)
    k.save()
    assert os.path.exists(statefile)
    # no leftover temp file
    assert not os.path.exists(statefile + ".tmp")


def test_reboot_flag(shell):
    shell.kernel.session = shell.kernel.make_session("root")
    out, code = run(shell, "reboot")
    assert code == 0
    assert shell.request_exit is True
    assert shell.kernel.reboot_requested is True


def test_shutdown_requires_root(shell):
    out, code = run(shell, "shutdown now")
    assert code == 1
    assert "permission denied" in out.lower()
    assert shell.request_exit is False
