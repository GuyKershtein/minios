from conftest import run

from minios.filesystem.filesystem import ROOT_CRED


def _root(kernel):
    kernel.session = kernel.make_session("root")


def _read(kernel, path):
    return kernel.fs.read(path, "/", ROOT_CRED)


# -- boot state ------------------------------------------------------------
def test_enabled_services_start_at_boot(kernel):
    sshd = kernel.services.get("sshd")
    assert sshd.enabled
    assert sshd.active
    assert sshd.main_pid is not None
    # sshd opened its listening socket
    assert any(s.local_port == 22 for s in kernel.net.sockets)
    # sshd process is in the table
    assert kernel.procmgr.get(sshd.main_pid).command == "sshd"


def test_disabled_service_not_running(kernel):
    getty = kernel.services.get("getty")
    assert not getty.enabled
    assert not getty.active


# -- systemctl -------------------------------------------------------------
def test_status(shell):
    out, _ = run(shell, "systemctl status sshd")
    assert "sshd.service" in out
    assert "active (running)" in out
    assert "enabled" in out


def test_stop_requires_root(shell):
    out, code = run(shell, "systemctl stop sshd")
    assert code == 1
    assert "permission denied" in out.lower()
    assert shell.kernel.services.get("sshd").active


def test_stop_and_start(kernel, shell):
    _root(kernel)
    sshd = kernel.services.get("sshd")
    pid = sshd.main_pid
    out, code = run(shell, "systemctl stop sshd")
    assert code == 0
    assert not sshd.active
    assert kernel.procmgr.get(pid) is None
    assert not any(s.local_port == 22 for s in kernel.net.sockets)
    # start again
    run(shell, "systemctl start sshd")
    assert sshd.active
    assert any(s.local_port == 22 for s in kernel.net.sockets)


def test_restart_changes_pid(kernel, shell):
    _root(kernel)
    sshd = kernel.services.get("sshd")
    old = sshd.main_pid
    run(shell, "systemctl restart sshd")
    assert sshd.active
    assert sshd.main_pid != old


def test_enable_disable(kernel, shell):
    _root(kernel)
    run(shell, "systemctl disable cron")
    assert not kernel.services.get("cron").enabled
    out, code = run(shell, "systemctl is-enabled cron")
    assert "disabled" in out
    run(shell, "systemctl enable cron")
    assert kernel.services.get("cron").enabled


def test_list_units(shell):
    out, _ = run(shell, "systemctl list-units")
    assert "sshd.service" in out
    assert "cron.service" in out


# -- logging ---------------------------------------------------------------
def test_syslog_has_boot_and_service_entries(kernel):
    log = _read(kernel, "/var/log/syslog")
    assert "Started OpenSSH server daemon." in log


def test_kernel_log(shell):
    out, _ = run(shell, "dmesg")
    assert "MiniOS" in out and "booting" in out


def test_logger_and_journalctl(kernel, shell):
    run(shell, "logger -t mytag hello-from-test")
    out, _ = run(shell, "journalctl")
    assert "mytag: hello-from-test" in out


def test_journalctl_filter(kernel, shell):
    out, _ = run(shell, "journalctl -u OpenSSH")
    assert "Started OpenSSH" in out


def test_service_state_persists(tmp_path):
    from minios.kernel import Kernel
    statefile = str(tmp_path / "state.json")
    k1 = Kernel(statefile=statefile)
    k1.session = k1.make_session("root")
    k1.services.disable("cron")
    k1.services.stop("cron")
    k1.save()

    k2 = Kernel(statefile=statefile)
    k2.load()
    assert not k2.services.get("cron").enabled
    assert not k2.services.get("cron").active
