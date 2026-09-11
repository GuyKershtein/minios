"""Cross-subsystem integration tests for Phase 1.

These exercise the whole path: parse -> shell -> kernel syscalls -> filesystem,
plus the persistence round-trip (create state, save, reload, verify).
"""

import os
import tempfile

from conftest import run

from minios.kernel import Kernel
from minios.shell import Shell


def test_workflow_create_navigate_edit(shell):
    run(shell, "mkdir -p work/notes")
    run(shell, "cd work/notes")
    out, _ = run(shell, "pwd")
    assert out.strip() == "/home/user/work/notes"
    run(shell, "echo 'task one' > todo.txt")
    run(shell, "echo 'task two' >> todo.txt")
    out, _ = run(shell, "cat todo.txt")
    assert out == "task one\ntask two\n"
    out, _ = run(shell, "grep task todo.txt")
    assert out.count("task") == 2


def test_tree_reflects_state(shell):
    run(shell, "cd /home/user")
    run(shell, "mkdir -p a/b")
    run(shell, "touch a/b/leaf.txt")
    out, _ = run(shell, "tree a")
    assert "a" in out and "b" in out and "leaf.txt" in out


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        statefile = os.path.join(d, "state.json")

        k1 = Kernel(statefile=statefile)
        s1 = Shell(k1)
        run(s1, "mkdir /home/user/persisted")
        run(s1, "echo 'survives reboot' > /home/user/persisted/note.txt")
        run(s1, "export FAVORITE=minios")
        run(s1, "cd /home/user/persisted")
        assert k1.save()

        # "reboot": brand new kernel loading the same state file
        k2 = Kernel(statefile=statefile)
        assert k2.load()
        s2 = Shell(k2)
        out, _ = run(s2, "cat /home/user/persisted/note.txt")
        assert out == "survives reboot\n"
        out, _ = run(s2, "echo $FAVORITE")
        assert out.strip() == "minios"
        # cwd persisted too
        out, _ = run(s2, "pwd")
        assert out.strip() == "/home/user/persisted"


def test_permission_enforced_through_shell():
    # root creates a locked file, user cannot overwrite it
    k = Kernel(statefile=None)
    root_shell = Shell(k)
    k.session.username = "root"
    k.session.uid = 0
    k.session.gid = 0
    k.session.gids = (0,)
    run(root_shell, "echo secret > /root/locked.txt")
    run(root_shell, "chmod 600 /root/locked.txt")

    # drop to normal user
    k.session.username = "user"
    k.session.uid = 1000
    k.session.gid = 1000
    k.session.gids = (1000,)
    out, code = run(root_shell, "cat /root/locked.txt")
    assert "permission denied" in out.lower()
    assert code != 0
