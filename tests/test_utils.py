"""Phase 10: extra utilities and the text editor."""

from conftest import run

from minios.filesystem.filesystem import ROOT_CRED


def test_wc(shell):
    run(shell, "echo -e 'a\\nb\\nc' > /tmp/lines.txt")
    out, _ = run(shell, "wc -l /tmp/lines.txt")
    assert out.split()[0] == "3"


def test_sort(shell):
    run(shell, "echo -e 'banana\\napple\\ncherry' > /tmp/f.txt")
    out, _ = run(shell, "sort /tmp/f.txt")
    assert out.splitlines() == ["apple", "banana", "cherry"]


def test_sort_numeric_reverse(shell):
    run(shell, "echo -e '2\\n10\\n1' > /tmp/n.txt")
    out, _ = run(shell, "sort -n -r /tmp/n.txt")
    assert out.splitlines() == ["10", "2", "1"]


def test_uniq(shell):
    run(shell, "echo -e 'x\\nx\\ny' > /tmp/u.txt")
    out, _ = run(shell, "cat /tmp/u.txt | uniq")
    assert out.splitlines() == ["x", "y"]


def test_cut(shell):
    run(shell, "echo 'a:b:c' > /tmp/c.txt")
    out, _ = run(shell, "cut -d : -f 2 /tmp/c.txt")
    assert out.strip() == "b"


def test_tee(shell):
    out, _ = run(shell, "echo hello | tee /tmp/tee.txt")
    assert out.strip() == "hello"
    saved, _ = run(shell, "cat /tmp/tee.txt")
    assert saved.strip() == "hello"


def test_which_builtin(shell):
    out, _ = run(shell, "which ls")
    assert "built-in" in out


def test_which_installed(shell):
    shell.kernel.session = shell.kernel.make_session("root")
    run(shell, "apt install hello")
    out, code = run(shell, "which hello")
    assert code == 0
    assert "/usr/bin/hello" in out


def test_basename_dirname(shell):
    out, _ = run(shell, "basename /usr/local/bin/thing")
    assert out.strip() == "thing"
    out, _ = run(shell, "dirname /usr/local/bin/thing")
    assert out.strip() == "/usr/local/bin"


def test_pipeline_wc_grep(shell):
    run(shell, "echo -e 'apple\\nbanana\\navocado' > /tmp/fruit.txt")
    out, _ = run(shell, "cat /tmp/fruit.txt | grep a | wc -l")
    assert out.strip() == "3"


# -- editor ----------------------------------------------------------------
def test_editor_noninteractive_creates_file(shell):
    # no line_prompt -> reads piped stdin and saves (like cat > file)
    shell.kernel.line_prompt = None
    out, code = run(shell, "echo -e 'line one\\nline two' | nano /tmp/edited.txt")
    assert code == 0
    saved = shell.kernel.fs.read("/tmp/edited.txt", "/", ROOT_CRED)
    assert saved == "line one\nline two\n"


def test_editor_interactive(shell):
    # feed the editor a scripted session via line_prompt
    lines = iter(["first line", "second line", ":wq"])
    shell.kernel.line_prompt = lambda p="": next(lines)
    out, code = run(shell, "nano /tmp/interactive.txt")
    assert code == 0
    saved = shell.kernel.fs.read("/tmp/interactive.txt", "/", ROOT_CRED)
    assert saved == "first line\nsecond line\n"


def test_editor_edit_existing(shell):
    run(shell, "echo original > /tmp/pre.txt")   # created by the user (writable)
    lines = iter(["appended", ":wq"])
    shell.kernel.line_prompt = lambda p="": next(lines)
    run(shell, "nano /tmp/pre.txt")
    saved = shell.kernel.fs.read("/tmp/pre.txt", "/", ROOT_CRED)
    assert saved == "original\nappended\n"
