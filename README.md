# MiniOS — a Linux Operating System Simulator

MiniOS simulates the structure and behaviour of a small Linux distribution
inside an ordinary Python application. It is **not** a bootloader, kernel
module, VM or game engine — it is a self-contained simulation with real
internal state. When you `mkdir test` then `cd test`, it actually works,
because commands operate on a genuine in-memory operating system, not on
hardcoded strings.

## Running

```bash
python main.py                 # boot with persistence (~/.minios/state.json)
python main.py --fresh         # ignore any saved state
python main.py --no-persist    # don't load or save state
python main.py --no-animate    # skip the boot animation
```

Optional: install `prompt_toolkit` for arrow-key history
(`pip install prompt_toolkit`). Without it, the `history` command still works.

## Testing

```bash
pip install pytest
python -m pytest tests -q
```

## Architecture

MiniOS is layered and communicates by message passing, mirroring a real OS:

```
UI (Terminal REPL)      renders the prompt, reads a line, prints output
      │
Shell (minish)          parse → pipes / redirection / && || ; → run commands
      │  (ExecutionContext: stdin, stdout, stderr, kernel, session)
Kernel  (syscall layer) the single source of truth; enforces permissions,
      │                 mutates subsystems, writes logs
Subsystems              FileSystem  (Users · Processes · Memory · Disks ·
                        Network · Services · Packages · Logs — later phases)
```

**Golden rule:** commands never touch subsystem internals directly. They call
kernel syscalls (`sys_open_read`, `sys_readdir`, `sys_mkdir`, `sys_chdir`, …),
which check permissions and update the real filesystem. That is what makes
this a simulation rather than faked output.

## Layout

```
minios/
  main.py                      entrypoint: boot → shell REPL → save state
  minios/
    kernel/kernel.py           Kernel + syscall layer + persistence
    filesystem/
      inode.py                 Inode: type, mode, uid/gid, timestamps, content
      permissions.py           mode parsing/formatting + access checks
      filesystem.py            VFS: path resolution, tree ops, default FHS tree
    shell/
      parser.py                tokenizer → chains / pipelines / redirections
      shell.py                 interpreter: pipes, redirects, chaining, env
      commands/                one class per command, registry-based
    session.py                 current user, hostname, cwd, environment
    ui/terminal.py             boot banner, prompt rendering, REPL
  tests/                       per-subsystem + integration tests
```

## Implemented so far — Phase 1

- **Virtual filesystem**: inodes with type/mode/owner/timestamps/size, the
  Filesystem Hierarchy Standard tree (`/bin /etc /home /var/log /usr/bin` …),
  path resolution (absolute/relative, `.`/`..`), symbolic links, and
  permission-checked operations.
- **Permissions**: full `rwxrwxrwx` for owner/group/other, octal and symbolic
  `chmod`, real access enforcement (a normal user can't read a `600` root file).
- **Shell (minish)**: quoting (`'…'` / `"…"`), `$VAR`/`${VAR}`/`$?`/`~`
  expansion, pipes `|`, redirection `> >> <`, chaining `&& || ;`,
  `NAME=value` assignments, `--help`.
- **Commands**: `ls cd pwd mkdir touch cat cp mv rm rmdir find grep head tail
  echo clear tree chmod chown ln stat whoami hostname uname env export unset
  history help man exit`.
- **Terminal**: animated boot sequence, dynamic `user@host:cwd$` prompt
  (`#` for root), command history.
- **Persistence groundwork**: full state (filesystem + session + env + cwd +
  history) serializes to JSON and restores on next boot.

## Implemented — Phase 2 (users, groups, authentication)

- **User database** backed by real `/etc/passwd`, `/etc/group`, `/etc/shadow`
  files in the VFS (inspect with `cat /etc/passwd`); parsed on read, rewritten
  on change, and persisted for free.
- **Salted password hashing** (`$5$salt$digest`), with locked (`!`) / disabled
  (`*`) account support.
- **Login system**: boot → `minios login:` → password → shell. Default
  accounts: `root/root` and `user/user`.
- **Privilege enforcement**: root-only commands (`useradd`, `userdel`,
  `usermod`, `chown`, changing others' passwords) fail for normal users.
- **Commands**: `useradd userdel usermod passwd su id groups users whoami`.
  `su` opens a nested session (type `exit` to return); root may `su` to anyone
  without a password.
- **Auth logging** to `/var/log/auth.log` for logins, `su`, user creation and
  password changes.

## Implemented — Phases 3–10

- **Processes & scheduler** (`ps`, `top`/`htop`, `kill`, `killall`, `jobs`,
  `fg`, `bg`, `renice`, `sleep`, `sched`): a real process table (PID/PPID/UID/
  state/CPU/mem/nice/start-time), background jobs (`cmd &`), and a scheduler
  with round-robin **and** priority policies that accrues CPU time.
- **Memory / disk / /proc / /dev** (`free`, `df`, `du`, `lsblk`, `blkid`,
  `mount`, `umount`, `lscpu`, `uptime`, `who`): memory tracks live process RAM;
  `/proc/meminfo`, `/proc/cpuinfo`, `/proc/uptime`, `/proc/<pid>/status` are
  generated dynamically; `/dev/null`, `/dev/zero`, `/dev/random` behave.
- **Networking** (`ip`, `ifconfig`, `ping`, `ss`/`netstat`, `hostname`):
  `lo`/`eth0` interfaces, routing table, sockets, `/etc/hosts` resolution and
  simulated ICMP.
- **Package manager** (`apt`): a local repository; `install` resolves
  dependencies and writes real files into the VFS; `remove` deletes them.
- **Services & logging** (`systemctl`, `service`, `journalctl`, `dmesg`,
  `logger`): units really start/stop (spawn processes, open sockets, bring up
  interfaces); enabled units auto-start at boot; events log to `/var/log`.
- **Shell scripting**: `if/elif/else`, `for`, `while`, functions, `exit`/
  `return`/`break`/`continue`, `test`/`[ ]`, `$@`/`$#`/`$1`, command
  substitution `$(...)`, executing scripts and installed binaries.
- **Text editor** (`nano`/`edit`) and utilities (`wc`, `sort`, `uniq`, `cut`,
  `tee`, `which`, `date`, `basename`, `dirname`, `seq`, `yes`).
- **Power & persistence**: `shutdown`/`reboot`/`poweroff`/`sync`; the entire
  system state serializes to JSON with an **atomic** save and restores on boot.

## Roadmap — all phases complete

| Phase | Scope | |
|------:|-------|:-:|
| 1 | filesystem, shell, core commands, terminal | ✅ |
| 2 | users, groups, `/etc/passwd`/`shadow`, authentication, login | ✅ |
| 3 | processes, process table, scheduler (round-robin + priority) | ✅ |
| 4 | memory, disks, `/proc`, `/dev` | ✅ |
| 5 | networking (interfaces, routes, sockets, `ping`/`ip`/`ss`) | ✅ |
| 6 | package manager (`apt`) + local repository | ✅ |
| 7 | services (`systemctl`) + logging (`/var/log`) | ✅ |
| 8 | shell scripting + command substitution | ✅ |
| 9 | full persistence hardening (atomic save) | ✅ |
| 10 | text editor, extra utilities, docs, tests | ✅ |

**153 automated tests** cover every subsystem plus end-to-end integration and
persistence round-trips: `python -m pytest tests -q`.
