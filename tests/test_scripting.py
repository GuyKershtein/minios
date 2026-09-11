from conftest import run

from minios.filesystem.filesystem import ROOT_CRED


def script(shell, body, name="/home/user/s.sh", args=""):
    """Write a script into the VFS, mark it executable, and run it."""
    shell.kernel.fs.write(name, "/", ROOT_CRED, body, mode=0o755)
    shell.kernel.fs.chmod(name, ROOT_CRED, 0o755)
    return run(shell, f"{name} {args}".strip())


# -- test / [ ] ------------------------------------------------------------
def test_test_builtin(shell):
    _, code = run(shell, "test 1 -eq 1")
    assert code == 0
    _, code = run(shell, "test 1 -eq 2")
    assert code == 1
    _, code = run(shell, "[ abc = abc ]")
    assert code == 0
    _, code = run(shell, "[ -d /etc ]")
    assert code == 0
    _, code = run(shell, "[ -f /etc/nonexistent ]")
    assert code == 1


def test_true_false(shell):
    assert run(shell, "true")[1] == 0
    assert run(shell, "false")[1] == 1


# -- control flow ----------------------------------------------------------
def test_if_else(shell):
    out, _ = script(shell, "if [ 1 -eq 1 ]; then\n echo yes\nelse\n echo no\nfi\n")
    assert out.strip() == "yes"


def test_if_elif_else(shell):
    body = ("x=2\n"
            "if [ $x -eq 1 ]; then\n echo one\n"
            "elif [ $x -eq 2 ]; then\n echo two\n"
            "else\n echo other\nfi\n")
    out, _ = script(shell, body)
    assert out.strip() == "two"


def test_for_loop(shell):
    out, _ = script(shell, "for i in a b c; do\n echo item-$i\ndone\n")
    assert out.split() == ["item-a", "item-b", "item-c"]


def test_while_loop(shell):
    # a while loop that terminates by consuming a sentinel file
    body = ("touch /tmp/flag\n"
            "while [ -f /tmp/flag ]; do\n"
            "  echo tick\n"
            "  rm /tmp/flag\n"
            "done\n"
            "echo done\n")
    out, _ = script(shell, body)
    assert out.split() == ["tick", "done"]


def test_seq_command(shell):
    out, _ = run(shell, "seq 1 4")
    assert out.split() == ["1", "2", "3", "4"]


def test_command_substitution(shell):
    out, _ = run(shell, "echo user-is-$(whoami)")
    assert out.strip() == "user-is-user"


def test_for_with_command_substitution(shell):
    out, _ = script(shell, "for n in $(seq 1 3); do\n echo v$n\ndone\n")
    assert out.split() == ["v1", "v2", "v3"]


def test_functions(shell):
    body = ("greet() {\n echo hello $1\n}\n"
            "greet world\n"
            "greet minios\n")
    out, _ = script(shell, body)
    assert out.split() == ["hello", "world", "hello", "minios"]


def test_positional_params(shell):
    out, _ = script(shell, 'echo "$1 and $2 (# $#)"\n', args="alpha beta")
    assert out.strip() == "alpha and beta (# 2)"


def test_exit_code(shell):
    out, code = script(shell, "echo before\nexit 7\necho after\n")
    assert "before" in out
    assert "after" not in out
    assert code == 7


def test_variables_in_script(shell):
    out, _ = script(shell, "NAME=MiniOS\necho Running on $NAME\n")
    assert out.strip() == "Running on MiniOS"


# -- executing files -------------------------------------------------------
def test_script_not_executable(shell):
    shell.kernel.fs.write("/home/user/noexec.sh", "/", ROOT_CRED,
                          "echo hi\n", mode=0o644)
    shell.kernel.fs.chmod("/home/user/noexec.sh", ROOT_CRED, 0o644)
    out, code = run(shell, "/home/user/noexec.sh")
    assert code == 126
    assert "Permission denied" in out


def test_installed_binary_runs(shell):
    shell.kernel.session = shell.kernel.make_session("root")
    run(shell, "apt install hello")
    out, code = run(shell, "hello")
    assert code == 0
    assert "Hello, world!" in out


def test_function_persists_across_lines(shell):
    run(shell, "add() { echo $1$2; }")   # define interactively
    out, _ = run(shell, "add foo bar")
    assert out.strip() == "foobar"
