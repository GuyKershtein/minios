"""Linux-style permission handling.

Modes are stored as integers (e.g. 0o755). File type is tracked separately on
the inode, so this module deals purely with the rwx permission bits and with
translating between octal, symbolic ("rwxr-xr-x") and access checks.
"""

from __future__ import annotations

# Permission bit masks
R = 0b100
W = 0b010
X = 0b001

# Type characters used in the leading column of `ls -l`
TYPE_CHARS = {
    "file": "-",
    "dir": "d",
    "link": "l",
    "char": "c",
    "block": "b",
    "fifo": "p",
    "socket": "s",
}


def octal_field(bits: int) -> str:
    """Turn a single 3-bit field (0..7) into 'rwx' style text."""
    return (
        ("r" if bits & R else "-")
        + ("w" if bits & W else "-")
        + ("x" if bits & X else "-")
    )


def mode_to_string(mode: int, ftype: str = "file") -> str:
    """Render a full 10-char permission string, e.g. 'drwxr-xr-x'."""
    owner = octal_field((mode >> 6) & 0o7)
    group = octal_field((mode >> 3) & 0o7)
    other = octal_field(mode & 0o7)
    return TYPE_CHARS.get(ftype, "-") + owner + group + other


def parse_mode(spec: str, current: int = 0o644) -> int:
    """Parse a chmod argument.

    Supports octal (e.g. '755', '0644') and a useful subset of symbolic
    notation (e.g. 'u+x', 'go-w', 'a=rx', '+x').
    """
    spec = spec.strip()
    # Octal form
    if spec.isdigit():
        val = int(spec, 8)
        return val & 0o777

    mode = current & 0o777
    for clause in spec.split(","):
        clause = clause.strip()
        if not clause:
            continue
        i = 0
        who = ""
        while i < len(clause) and clause[i] in "ugoa":
            who += clause[i]
            i += 1
        if not who:
            who = "a"
        if i >= len(clause) or clause[i] not in "+-=":
            raise ValueError(f"invalid mode: '{spec}'")
        op = clause[i]
        i += 1
        perms = clause[i:]
        bits = 0
        for p in perms:
            if p == "r":
                bits |= R
            elif p == "w":
                bits |= W
            elif p == "x":
                bits |= X
            else:
                raise ValueError(f"invalid mode: '{spec}'")

        targets = set()
        for w in who:
            if w == "a":
                targets.update("ugo")
            else:
                targets.add(w)

        for t in targets:
            shift = {"u": 6, "g": 3, "o": 0}[t]
            field = (mode >> shift) & 0o7
            if op == "+":
                field |= bits
            elif op == "-":
                field &= ~bits
            else:  # '='
                field = bits
            mode = (mode & ~(0o7 << shift)) | (field << shift)
    return mode & 0o777


def _field_for(mode: int, level: str) -> int:
    shift = {"owner": 6, "group": 3, "other": 0}[level]
    return (mode >> shift) & 0o7


def access_level(inode_uid: int, inode_gid: int, uid: int, gids) -> str:
    """Which permission field applies for a given accessing user."""
    if uid == 0:
        return "owner"  # root; callers usually bypass checks anyway
    if uid == inode_uid:
        return "owner"
    if inode_gid in set(gids):
        return "group"
    return "other"


def can(inode, need: int, uid: int, gids) -> bool:
    """Check whether ``uid`` (with supplementary ``gids``) has ``need`` (R/W/X)
    permission on ``inode``. Root (uid 0) may do anything."""
    if uid == 0:
        # root bypasses read/write; keep X honest so non-executables aren't "runnable"
        if need == X:
            return bool(inode.mode & 0o111)
        return True
    level = access_level(inode.uid, inode.gid, uid, gids)
    field = _field_for(inode.mode, level)
    return (field & need) == need
