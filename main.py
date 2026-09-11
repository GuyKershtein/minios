#!/usr/bin/env python3
"""MiniOS entry point.

Boots the simulated OS, restores saved state if present, and drops the user
into an interactive shell. State is persisted on exit.

Usage:
    python main.py                 # boot with persistence (~/.minios/state.json)
    python main.py --fresh         # ignore any saved state
    python main.py --no-persist    # do not load or save state
    python main.py --state PATH    # use a custom state file
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minios.kernel import Kernel          # noqa: E402
from minios.ui import Terminal            # noqa: E402


def default_statefile():
    home = os.path.expanduser("~")
    return os.path.join(home, ".minios", "state.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description="MiniOS — a Linux simulator")
    ap.add_argument("--state", default=default_statefile(),
                    help="path to the persistent state file")
    ap.add_argument("--fresh", action="store_true",
                    help="start from a clean filesystem, ignoring saved state")
    ap.add_argument("--no-persist", action="store_true",
                    help="neither load nor save state")
    ap.add_argument("--no-animate", action="store_true",
                    help="skip the animated boot delay")
    ap.add_argument("--login", action="store_true",
                    help="always show the interactive login prompt")
    ap.add_argument("--user", default="user",
                    help="auto-login as this user when input is not a TTY")
    args = ap.parse_args(argv)

    statefile = None if args.no_persist else args.state
    kernel = Kernel(statefile=statefile)
    if statefile and not args.fresh:
        try:
            if kernel.load():
                pass
        except Exception as e:
            print(f"MiniOS: could not load saved state ({e}); starting fresh.")

    term = Terminal(kernel, animate=not args.no_animate,
                    force_login=args.login, default_user=args.user)
    term.run()


if __name__ == "__main__":
    main()
