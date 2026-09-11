from conftest import run


def test_echo(shell):
    out, code = run(shell, "echo hello world")
    assert out == "hello world\n"
    assert code == 0


def test_pwd_and_cd(shell):
    out, _ = run(shell, "pwd")
    assert out.strip() == "/home/user"
    run(shell, "mkdir demo")
    run(shell, "cd demo")
    out, _ = run(shell, "pwd")
    assert out.strip() == "/home/user/demo"


def test_mkdir_then_ls(shell):
    run(shell, "mkdir project")
    out, _ = run(shell, "ls")
    assert "project" in out.split()


def test_touch_then_ls(shell):
    run(shell, "touch file.txt")
    out, _ = run(shell, "ls")
    assert "file.txt" in out.split()


def test_redirect_and_cat(shell):
    run(shell, "echo hello > greeting.txt")
    out, _ = run(shell, "cat greeting.txt")
    assert out == "hello\n"


def test_append_redirect(shell):
    run(shell, "echo one > log.txt")
    run(shell, "echo two >> log.txt")
    out, _ = run(shell, "cat log.txt")
    assert out == "one\ntwo\n"


def test_pipe_grep(shell):
    run(shell, "echo hello > a.txt")
    run(shell, "echo world >> a.txt")
    out, _ = run(shell, "cat a.txt | grep world")
    assert out == "world\n"


def test_input_redirect(shell):
    run(shell, "echo needle > hay.txt")
    out, _ = run(shell, "grep needle < hay.txt")
    assert out == "needle\n"


def test_env_var_expansion(shell):
    run(shell, "export NAME=MiniOS")
    out, _ = run(shell, "echo $NAME rules")
    assert out == "MiniOS rules\n"


def test_home_expansion(shell):
    out, _ = run(shell, "echo $HOME")
    assert out.strip() == "/home/user"
    out, _ = run(shell, "echo ~")
    assert out.strip() == "/home/user"


def test_chaining_and(shell):
    out, _ = run(shell, "echo a && echo b")
    assert out == "a\nb\n"


def test_chaining_or(shell):
    out, _ = run(shell, "nosuchcmd || echo fallback")
    assert "fallback" in out


def test_semicolon(shell):
    out, _ = run(shell, "echo one ; echo two")
    assert out == "one\ntwo\n"


def test_exit_code_variable(shell):
    run(shell, "nosuchcmd")
    out, _ = run(shell, "echo $?")
    assert out.strip() == "127"


def test_quoting(shell):
    out, _ = run(shell, 'echo "hello   world"')
    assert out == "hello   world\n"
    out, _ = run(shell, "echo 'no $HOME expand'")
    assert out == "no $HOME expand\n"


def test_command_not_found(shell):
    out, code = run(shell, "definitelynotacommand")
    assert "command not found" in out
    assert code == 127


def test_chmod_via_shell(shell):
    run(shell, "touch script.sh")
    run(shell, "chmod 755 script.sh")
    out, _ = run(shell, "ls -l script.sh")
    assert out.startswith("-rwxr-xr-x")
