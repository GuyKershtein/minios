from conftest import run


# -- UserDB / authentication -----------------------------------------------
def test_default_accounts_exist(kernel):
    names = {u.name for u in kernel.userdb.users()}
    assert {"root", "user"} <= names
    root = kernel.userdb.get_user("root")
    assert root.uid == 0 and root.home == "/root"


def test_passwd_file_readable(shell):
    out, _ = run(shell, "cat /etc/passwd")
    assert "root:x:0:0" in out
    assert "user:x:1000:1000" in out


def test_authentication(kernel):
    assert kernel.authenticate("user", "user")
    assert kernel.authenticate("root", "root")
    assert not kernel.authenticate("user", "wrong")
    assert not kernel.authenticate("nobody", "x")


def test_groups_of(kernel):
    _, gids = kernel.userdb.groups_of("user")
    # user's primary group plus the sudo group it belongs to
    assert 1000 in gids
    assert kernel.userdb.get_group(name="sudo").gid in gids


# -- id / groups -----------------------------------------------------------
def test_id_command(shell):
    out, _ = run(shell, "id")
    assert "uid=1000(user)" in out
    assert "gid=1000(user)" in out


def test_groups_command(shell):
    out, _ = run(shell, "groups")
    assert "user" in out.split()
    assert "sudo" in out.split()


# -- privilege enforcement -------------------------------------------------
def test_useradd_denied_for_normal_user(shell):
    out, code = run(shell, "useradd bob")
    assert "permission denied" in out.lower()
    assert code == 1
    assert shell.kernel.userdb.get_user("bob") is None


def _become_root(kernel):
    kernel.session = kernel.make_session("root")


def test_useradd_as_root(kernel, shell):
    _become_root(kernel)
    out, code = run(shell, "useradd -m bob")
    assert code == 0
    bob = kernel.userdb.get_user("bob")
    assert bob is not None
    # home directory was created and owned by bob
    home = kernel.fs.resolve(bob.home)
    assert home.uid == bob.uid


def test_passwd_and_login_flow(kernel, shell):
    _become_root(kernel)
    run(shell, "useradd -m alice")
    out, code = run(shell, "passwd alice s3cret")   # non-interactive form
    assert code == 0
    assert kernel.authenticate("alice", "s3cret")
    assert not kernel.authenticate("alice", "nope")


def test_su_switches_user(kernel, shell):
    # start as normal user, su to root (provide password via prompt hook)
    kernel.password_prompt = lambda p="": "root"
    assert kernel.session.username == "user"
    out, code = run(shell, "su root")
    assert code == 0
    assert kernel.session.username == "root"
    assert kernel.session.is_root
    # exit returns to the previous user rather than halting
    run(shell, "exit")
    assert kernel.session.username == "user"


def test_su_wrong_password(kernel, shell):
    kernel.password_prompt = lambda p="": "wrong"
    out, code = run(shell, "su root")
    assert code == 1
    assert "authentication failure" in out.lower()
    assert kernel.session.username == "user"


def test_root_prompt_marker(kernel):
    _become_root(kernel)
    assert kernel.session.is_root


def test_normal_user_cannot_useradd_via_group(kernel, shell):
    # even a member of 'sudo' cannot useradd directly (no sudo command)
    out, code = run(shell, "useradd charlie")
    assert code == 1


def test_auth_log_written(kernel, shell):
    kernel.authenticate("user", "user")
    log = _read(kernel, "/var/log/auth.log")
    assert "authentication success for user user" in log


def _read(kernel, path):
    from minios.filesystem.filesystem import ROOT_CRED
    return kernel.fs.read(path, "/", ROOT_CRED)
