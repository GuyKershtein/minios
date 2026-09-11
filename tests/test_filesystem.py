import pytest

from minios.filesystem import FileSystem, FSError
from minios.filesystem.filesystem import ROOT_CRED, _Cred


def test_default_tree_exists():
    fs = FileSystem()
    for path in ("/bin", "/etc", "/home/user", "/var/log", "/usr/bin", "/tmp"):
        assert fs.exists(path), path
    assert fs.resolve("/tmp").is_dir


def test_mkdir_and_resolve():
    fs = FileSystem()
    fs.mkdir("/home/user/projects", ROOT_CRED)
    node = fs.resolve("/home/user/projects")
    assert node.is_dir
    assert fs.path_of(node) == "/home/user/projects"


def test_mkdir_parents():
    fs = FileSystem()
    fs.mkdir("/a/b/c/d", ROOT_CRED, parents=True)
    assert fs.exists("/a/b/c/d")


def test_write_then_read():
    fs = FileSystem()
    fs.write("/tmp/hello.txt", "/", ROOT_CRED, "hello world")
    assert fs.read("/tmp/hello.txt", "/", ROOT_CRED) == "hello world"


def test_append():
    fs = FileSystem()
    fs.write("/tmp/a", "/", ROOT_CRED, "one\n")
    fs.write("/tmp/a", "/", ROOT_CRED, "two\n", append=True)
    assert fs.read("/tmp/a", "/", ROOT_CRED) == "one\ntwo\n"


def test_relative_paths():
    fs = FileSystem()
    fs.mkdir("/home/user/x", ROOT_CRED)
    node = fs.resolve("x", cwd="/home/user")
    assert node.name == "x"
    parent = fs.resolve("..", cwd="/home/user/x")
    assert fs.path_of(parent) == "/home/user"


def test_remove_and_rmdir():
    fs = FileSystem()
    fs.write("/tmp/f", "/", ROOT_CRED, "x")
    fs.remove("/tmp/f", "/", ROOT_CRED)
    assert not fs.exists("/tmp/f")
    fs.mkdir("/tmp/d", ROOT_CRED)
    fs.rmdir("/tmp/d", "/", ROOT_CRED)
    assert not fs.exists("/tmp/d")


def test_rmdir_nonempty_fails():
    fs = FileSystem()
    fs.mkdir("/tmp/d", ROOT_CRED)
    fs.write("/tmp/d/f", "/", ROOT_CRED, "x")
    with pytest.raises(FSError):
        fs.rmdir("/tmp/d", "/", ROOT_CRED)


def test_move_and_copy():
    fs = FileSystem()
    fs.write("/tmp/src", "/", ROOT_CRED, "data")
    fs.copy("/tmp/src", "/tmp/copy", "/", ROOT_CRED)
    assert fs.read("/tmp/copy", "/", ROOT_CRED) == "data"
    fs.move("/tmp/src", "/tmp/moved", "/", ROOT_CRED)
    assert not fs.exists("/tmp/src")
    assert fs.read("/tmp/moved", "/", ROOT_CRED) == "data"


def test_symlink_resolution():
    fs = FileSystem()
    fs.write("/tmp/real", "/", ROOT_CRED, "target-data")
    fs.symlink("/tmp/real", "/tmp/link", "/", ROOT_CRED)
    assert fs.read("/tmp/link", "/", ROOT_CRED) == "target-data"
    link = fs.stat("/tmp/link", "/", ROOT_CRED, follow=False)
    assert link.is_link


def test_permission_denied_write():
    fs = FileSystem()
    # a file owned by root, mode 600, cannot be written by a normal user
    fs.write("/tmp/secret", "/", ROOT_CRED, "top")
    fs.chmod("/tmp/secret", ROOT_CRED, 0o600)
    user = _Cred(1000, (1000,))
    with pytest.raises(FSError):
        fs.write("/tmp/secret", "/", user, "hacked", create=False)


def test_serialization_roundtrip():
    fs = FileSystem()
    fs.mkdir("/home/user/keep", ROOT_CRED)
    fs.write("/home/user/keep/data.txt", "/", ROOT_CRED, "persist me")
    d = fs.to_dict()
    fs2 = FileSystem.from_dict(d)
    assert fs2.read("/home/user/keep/data.txt", "/", ROOT_CRED) == "persist me"
