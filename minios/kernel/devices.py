"""Behaviour for the special files under /dev.

The device nodes themselves are real inodes (created at boot so ``ls /dev``
works); this module supplies the *behaviour* of reading/writing the special
ones: /dev/null, /dev/zero, /dev/random, /dev/urandom, /dev/tty.
"""

from __future__ import annotations

import os

# how many bytes generators like /dev/zero return per read (bounded so we
# don't produce an infinite stream in a simulator)
_CHUNK = 512

SPECIAL = {"/dev/null", "/dev/zero", "/dev/full", "/dev/random",
           "/dev/urandom", "/dev/tty"}


class DevFS:
    def __init__(self, kernel):
        self.kernel = kernel

    def handles_read(self, abspath):
        return abspath in SPECIAL

    def handles_write(self, abspath):
        return abspath in ("/dev/null", "/dev/full", "/dev/tty")

    def read(self, abspath):
        if abspath == "/dev/null":
            return ""
        if abspath == "/dev/zero":
            return "\0" * _CHUNK
        if abspath in ("/dev/random", "/dev/urandom"):
            return os.urandom(_CHUNK).hex()
        if abspath == "/dev/tty":
            return ""
        return ""

    def write(self, abspath, data):
        # /dev/null and /dev/tty accept and discard; /dev/full always fails
        if abspath == "/dev/full":
            from ..filesystem import FSError
            raise FSError("/dev/full: No space left on device")
        return len(data)
