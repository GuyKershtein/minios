from minios.filesystem import permissions as perm
from minios.filesystem.inode import Inode


def test_mode_to_string_file():
    assert perm.mode_to_string(0o644, "file") == "-rw-r--r--"
    assert perm.mode_to_string(0o755, "dir") == "drwxr-xr-x"
    assert perm.mode_to_string(0o777, "link") == "lrwxrwxrwx"
    assert perm.mode_to_string(0o600, "file") == "-rw-------"


def test_parse_octal():
    assert perm.parse_mode("755") == 0o755
    assert perm.parse_mode("0644") == 0o644
    assert perm.parse_mode("600") == 0o600


def test_parse_symbolic():
    assert perm.parse_mode("u+x", 0o644) == 0o744
    assert perm.parse_mode("go-r", 0o666) == 0o622
    assert perm.parse_mode("a=rx", 0o000) == 0o555
    assert perm.parse_mode("+x", 0o644) == 0o755


def test_can_owner_group_other():
    node = Inode("file", 0o640, uid=1000, gid=1000)
    # owner can read/write, not execute
    assert perm.can(node, perm.R, 1000, (1000,))
    assert perm.can(node, perm.W, 1000, (1000,))
    assert not perm.can(node, perm.X, 1000, (1000,))
    # group member can read only
    assert perm.can(node, perm.R, 1001, (1000,))
    assert not perm.can(node, perm.W, 1001, (1000,))
    # other cannot read
    assert not perm.can(node, perm.R, 1002, (1002,))


def test_root_bypasses_read_write():
    node = Inode("file", 0o000, uid=1000, gid=1000)
    assert perm.can(node, perm.R, 0, (0,))
    assert perm.can(node, perm.W, 0, (0,))
    # but a non-executable file is still not executable for root
    assert not perm.can(node, perm.X, 0, (0,))
