from conftest import run


# -- memory ----------------------------------------------------------------
def test_free_shows_memory(shell):
    out, _ = run(shell, "free")
    assert "Mem:" in out and "Swap:" in out
    assert "total" in out


def test_memory_tracks_processes(kernel):
    before = kernel.memory.used_kb()
    kernel.procmgr.spawn("hog", ["hog"], mem_kb=100000, state="R")
    after = kernel.memory.used_kb()
    assert after > before


def test_meminfo_proc(shell):
    out, _ = run(shell, "cat /proc/meminfo")
    assert "MemTotal:" in out
    assert "MemFree:" in out


# -- disks -----------------------------------------------------------------
def test_df_lists_root(shell):
    out, _ = run(shell, "df -h")
    assert "/dev/sda1" in out
    assert "Mounted on" in out


def test_lsblk(shell):
    out, _ = run(shell, "lsblk")
    assert "sda" in out and "sda1" in out and "sdb" in out


def test_blkid_has_uuids(shell):
    out, _ = run(shell, "blkid")
    assert "/dev/sda1" in out and "UUID=" in out


def test_mount_umount(shell):
    kernel = shell.kernel
    kernel.session.uid = 0  # need root to mount
    run(shell, "mkdir /mnt/data")
    out, code = run(shell, "mount /dev/sdb1 /mnt/data")
    assert code == 0
    assert kernel.disks.mount_at("/mnt/data") is not None
    out, _ = run(shell, "df")
    assert "/mnt/data" in out
    out, code = run(shell, "umount /mnt/data")
    assert code == 0
    assert kernel.disks.mount_at("/mnt/data") is None


def test_du_reports_sizes(shell):
    run(shell, "echo hello-there > /tmp/f.txt")
    out, _ = run(shell, "du -s /tmp")
    assert "/tmp" in out


# -- /proc -----------------------------------------------------------------
def test_proc_uptime(shell):
    out, _ = run(shell, "cat /proc/uptime")
    assert len(out.split()) == 2


def test_proc_version(shell):
    out, _ = run(shell, "cat /proc/version")
    assert "MiniOS" in out


def test_proc_pid_status(shell):
    out, _ = run(shell, "cat /proc/1/status")
    assert "Name:" in out and "init" in out
    assert "Pid:\t1" in out


def test_proc_listing_includes_pids(shell):
    out, _ = run(shell, "ls /proc")
    assert "meminfo" in out.split()
    assert "1" in out.split()   # init's pid dir


# -- /dev ------------------------------------------------------------------
def test_dev_nodes_exist(shell):
    out, _ = run(shell, "ls /dev")
    for dev in ("null", "zero", "random", "sda", "sda1"):
        assert dev in out.split()


def test_dev_null_read_write(shell):
    out, _ = run(shell, "cat /dev/null")
    assert out == ""
    # writing to /dev/null discards
    out, code = run(shell, "echo discarded > /dev/null")
    assert code == 0
    out, _ = run(shell, "cat /dev/null")
    assert out == ""


def test_dev_zero_read(shell):
    out, _ = run(shell, "cat /dev/zero")
    assert "\0" in out


# -- misc ------------------------------------------------------------------
def test_uptime_command(shell):
    out, _ = run(shell, "uptime")
    assert "up" in out and "load average" in out


def test_lscpu(shell):
    out, _ = run(shell, "lscpu")
    assert "Architecture:" in out and "x86_64" in out
