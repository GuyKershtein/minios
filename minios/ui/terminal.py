"""The interactive terminal: boot banner, prompt rendering and the REPL.

Arrow-key history uses prompt_toolkit if it happens to be installed, otherwise
it falls back to a plain ``input()`` loop (the ``history`` command still works
either way).
"""

from __future__ import annotations

import getpass
import sys
import time

from ..shell import Shell

_BOOT_STEPS = [
    "Starting MiniOS kernel",
    "Initializing memory",
    "Detecting virtual disks",
    "Mounting filesystems",
    "Starting networking",
    "Starting system services",
    "Starting shell",
]

# ANSI colors
GREEN = "\x1b[1;32m"
BLUE = "\x1b[1;34m"
RED = "\x1b[1;31m"
RESET = "\x1b[0m"


class Terminal:
    def __init__(self, kernel, use_color=True, animate=True,
                 force_login=False, default_user="user"):
        self.kernel = kernel
        self.shell = Shell(kernel)
        self.use_color = use_color and sys.stdout.isatty()
        self.animate = animate
        self.force_login = force_login
        self.default_user = default_user
        # let interactive commands (su/passwd) read input from the real terminal
        kernel.password_prompt = self._read_password
        kernel.line_prompt = self._read_line

    def _read_password(self, prompt="Password: "):
        # getpass reads the console directly and would block on piped (non-TTY)
        # input, so only use it for a real terminal.
        if not sys.stdin.isatty():
            try:
                return input(prompt).lstrip("﻿")
            except EOFError:
                return ""
        try:
            return getpass.getpass(prompt)
        except Exception:
            return input(prompt)

    def _read_line(self, prompt=""):
        return input(prompt).lstrip("﻿")

    # -- boot -------------------------------------------------------------
    def boot(self):
        ok = f"[{GREEN} OK {RESET}]" if self.use_color else "[ OK ]"
        print()
        for step in _BOOT_STEPS:
            print(f"{ok} {step}")
            if self.animate:
                time.sleep(0.06)
        print()
        try:
            motd = self.kernel.sys_open_read("/etc/motd")
            print(motd)
        except Exception:
            pass

    # -- login ------------------------------------------------------------
    def login(self):
        """Authenticate a user and install their session.

        When input is not a TTY (e.g. a piped script) and --login was not
        requested, auto-login as the default user so demos/scripts still work.
        """
        interactive = self.force_login or sys.stdin.isatty()
        if not interactive:
            self._set_user(self.default_user)
            return True

        print("(default accounts: root/root, user/user)\n")
        while True:
            try:
                username = input(f"{self.kernel.HOSTNAME} login: ").lstrip("﻿").strip()
            except EOFError:
                return False
            if not username:
                continue
            password = self._read_password("Password: ")
            if self.kernel.userdb.get_user(username) and \
                    self.kernel.authenticate(username, password):
                self._set_user(username)
                print(f"\nLast login: {time.ctime()} on tty1")
                return True
            print("Login incorrect\n")

    def _set_user(self, username):
        self.kernel.session = self.kernel.make_session(username, login=True)
        self.kernel.log("auth", f"user {username} logged in")

    # -- prompt -----------------------------------------------------------
    def prompt(self):
        s = self.kernel.session
        mark = "#" if s.is_root else "$"
        user_host = f"{s.username}@{s.hostname}"
        cwd = s.display_cwd()
        if self.use_color:
            uh = GREEN + user_host + RESET
            path = BLUE + cwd + RESET
            return f"{uh}:{path}{mark} "
        return f"{user_host}:{cwd}{mark} "

    # -- main loop --------------------------------------------------------
    def run(self):
        while True:
            self._session_loop()
            if self.kernel.reboot_requested:
                self.kernel.reboot_requested = False
                self.shell.request_exit = False
                print("\nRebooting MiniOS...\n")
                self.kernel.boot_epoch = time.time()
                continue
            break

    def _session_loop(self):
        self.boot()
        if not self.login():
            print("\nNo login. Halting.")
            return
        pt_session = self._make_prompt_toolkit()
        while not self.shell.request_exit:
            try:
                if pt_session is not None:
                    line = pt_session.prompt(self._plain_prompt())
                else:
                    line = input(self.prompt())
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("^C")
                continue

            out, _ = self.shell.execute_line(line)
            if out:
                sys.stdout.write(out)
                if not out.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()

        self.shutdown()

    def _plain_prompt(self):
        s = self.kernel.session
        mark = "#" if s.is_root else "$"
        return f"{s.username}@{s.hostname}:{s.display_cwd()}{mark} "

    def _make_prompt_toolkit(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            hist = InMemoryHistory()
            for line in self.kernel.session.history:
                hist.append_string(line)
            return PromptSession(history=hist)
        except Exception:
            return None

    def shutdown(self):
        print("\nSaving system state...")
        try:
            if self.kernel.save():
                print("MiniOS: state saved. Goodbye.")
            else:
                print("MiniOS: halted.")
        except Exception as e:
            print(f"MiniOS: could not save state: {e}")
