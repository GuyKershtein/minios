from conftest import run

from minios.packages.package_manager import PackageError


def _root(kernel):
    kernel.session = kernel.make_session("root")


# -- repository ------------------------------------------------------------
def test_repository_has_packages(kernel):
    names = {p.name for p in kernel.pkg.repo.all()}
    assert {"nano", "git", "htop", "hello"} <= names


def test_search(shell):
    out, _ = run(shell, "apt search editor")
    assert "nano" in out
    assert "vim" in out


def test_show(shell):
    out, _ = run(shell, "apt show git")
    assert "Package: git" in out
    assert "Depends: curl" in out


# -- install / remove ------------------------------------------------------
def test_install_requires_root(shell):
    out, code = run(shell, "apt install hello")
    assert code == 1
    assert "permission denied" in out.lower()
    assert not shell.kernel.pkg.is_installed("hello")


def test_install_creates_files(kernel, shell):
    _root(kernel)
    out, code = run(shell, "apt install hello")
    assert code == 0
    assert kernel.pkg.is_installed("hello")
    # the package's file was really written into the VFS
    assert kernel.fs.exists("/usr/bin/hello")


def test_install_resolves_dependencies(kernel, shell):
    _root(kernel)
    out, code = run(shell, "apt install git")
    assert code == 0
    # git depends on curl -> both installed
    assert kernel.pkg.is_installed("git")
    assert kernel.pkg.is_installed("curl")
    assert kernel.fs.exists("/usr/bin/curl")


def test_remove_deletes_files(kernel, shell):
    _root(kernel)
    run(shell, "apt install hello")
    assert kernel.fs.exists("/usr/bin/hello")
    out, code = run(shell, "apt remove hello")
    assert code == 0
    assert not kernel.pkg.is_installed("hello")
    assert not kernel.fs.exists("/usr/bin/hello")


def test_remove_blocked_by_dependency(kernel, shell):
    _root(kernel)
    run(shell, "apt install git")
    # curl is required by git; removing it should fail
    out, code = run(shell, "apt remove curl")
    assert code == 1
    assert "depends on curl" in out


def test_install_unknown_package(kernel, shell):
    _root(kernel)
    out, code = run(shell, "apt install nonexistent")
    assert code == 1
    assert "Unable to locate package" in out


def test_list_installed(kernel, shell):
    _root(kernel)
    run(shell, "apt install htop")
    out, _ = run(shell, "apt list --installed")
    assert "htop" in out


def test_install_persists(tmp_path):
    from minios.kernel import Kernel
    statefile = str(tmp_path / "state.json")
    k1 = Kernel(statefile=statefile)
    k1.session = k1.make_session("root")
    k1.pkg.install("cowsay")
    k1.save()

    k2 = Kernel(statefile=statefile)
    k2.load()
    assert k2.pkg.is_installed("cowsay")
    assert k2.fs.exists("/usr/bin/cowsay")
