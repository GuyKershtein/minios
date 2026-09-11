from conftest import run

from minios.kernel.process import SIGKILL, SIGSTOP, SIGCONT


# -- process table ---------------------------------------------------------
def test_init_and_shell_seeded(kernel):
    procs = {p.command: p for p in kernel.procmgr.all()}
    assert "init" in procs
    assert procs["init"].pid == 1
    assert procs["init"].uid == 0
    assert "minish" in procs


def test_ps_lists_processes(shell):
    out, _ = run(shell, "ps")
    assert "PID" in out and "COMMAND" in out
    assert "init" in out
    assert "minish" in out


def test_ps_aux_has_cpu_mem(shell):
    out, _ = run(shell, "ps aux")
    assert "%CPU" in out and "%MEM" in out


def test_spawn_and_kill(kernel):
    p = kernel.procmgr.spawn("worker", ["worker"], state="R")
    assert kernel.procmgr.get(p.pid) is not None
    kernel.procmgr.kill(p.pid, SIGKILL)
    assert kernel.procmgr.get(p.pid) is None


def test_cannot_kill_init(kernel):
    import pytest
    with pytest.raises(PermissionError):
        kernel.procmgr.kill(1)


def test_stop_and_continue(kernel):
    p = kernel.procmgr.spawn("svc", ["svc"], state="R")
    kernel.procmgr.kill(p.pid, SIGSTOP)
    assert kernel.procmgr.get(p.pid).state == "T"
    kernel.procmgr.kill(p.pid, SIGCONT)
    assert kernel.procmgr.get(p.pid).state == "R"


def test_kill_permission_denied_for_other_user(kernel):
    # a process owned by root cannot be killed by the normal user session
    import pytest
    p = kernel.procmgr.spawn("rootproc", ["rootproc"], uid=0, state="R")
    assert kernel.session.uid == 1000
    with pytest.raises(PermissionError):
        kernel.procmgr.kill(p.pid)


# -- background jobs -------------------------------------------------------
def test_background_job(shell):
    out, _ = run(shell, "sleep 5 &")
    assert out.startswith("[1]")
    out, _ = run(shell, "jobs")
    assert "sleep 5" in out


def test_background_job_finishes_over_time(shell):
    run(shell, "sleep 3 &")
    kernel = shell.kernel
    jobpids = [p.pid for p in kernel.procmgr.jobs()]
    assert jobpids
    kernel.procmgr.scheduler.tick(30)   # let simulated time pass
    # the finite sleep job should have completed and left the table
    assert all(kernel.procmgr.get(pid) is None for pid in jobpids)


# -- scheduler -------------------------------------------------------------
def test_scheduler_round_robin(kernel):
    a = kernel.procmgr.spawn("a", ["a"], state="R")
    b = kernel.procmgr.spawn("b", ["b"], state="R")
    kernel.procmgr.scheduler.policy = "rr"
    kernel.procmgr.scheduler.tick(40)
    # both processes should have accumulated CPU time under round-robin
    assert a.cpu_ticks > 0
    assert b.cpu_ticks > 0


def test_scheduler_priority(kernel):
    lo = kernel.procmgr.spawn("lowprio", ["lowprio"], state="R", nice=10)
    hi = kernel.procmgr.spawn("hiprio", ["hiprio"], state="R", nice=-5)
    kernel.procmgr.scheduler.policy = "priority"
    kernel.procmgr.scheduler.tick(20)
    # the higher-priority (lower nice) process should dominate the CPU
    assert hi.cpu_ticks > lo.cpu_ticks


def test_sched_command_output(shell):
    run(shell, "sleep 100 &")
    out, _ = run(shell, "sched")
    assert "CPU 0" in out
    assert "policy=" in out


def test_renice(shell):
    p = shell.kernel.procmgr.spawn("target", ["target"], state="R", nice=0)
    shell.kernel.session.uid = 0  # act as root to lower nice
    out, code = run(shell, f"renice -5 {p.pid}")
    assert code == 0
    assert p.nice == -5


def test_persistence_of_processes(tmp_path):
    from minios.kernel import Kernel
    statefile = str(tmp_path / "state.json")
    k1 = Kernel(statefile=statefile)
    p = k1.procmgr.spawn("daemon", ["daemon"], state="R")
    pid = p.pid
    k1.save()

    k2 = Kernel(statefile=statefile)
    k2.load()
    assert k2.procmgr.get(pid) is not None
    assert k2.procmgr.get(pid).command == "daemon"
