"""User and group management commands.

These operate on the real user database (``/etc/passwd`` etc.) through the
kernel, and enforce root privilege where Linux would.
"""

from __future__ import annotations

from ...users.userdb import UserDBError
from .base import Command


class Id(Command):
    name = "id"
    synopsis = "id [user]"
    help_text = "Print user and group IDs."

    def run(self, ctx):
        db = ctx.kernel.userdb
        if len(ctx.argv) > 1:
            u = db.get_user(ctx.argv[1])
            if not u:
                ctx.errorln(f"id: '{ctx.argv[1]}': no such user")
                return 1
            uid, gid = u.uid, u.gid
            _, gids = db.groups_of(u.name)
        else:
            uid, gid = ctx.session.uid, ctx.session.gid
            gids = ctx.session.gids
        grouplist = ",".join(f"{g}({db.gname(g)})" for g in gids)
        ctx.writeln(f"uid={uid}({db.uname(uid)}) gid={gid}({db.gname(gid)}) "
                    f"groups={grouplist}")
        return 0


class Groups(Command):
    name = "groups"
    synopsis = "groups [user]"
    help_text = "Print the groups a user belongs to."

    def run(self, ctx):
        db = ctx.kernel.userdb
        name = ctx.argv[1] if len(ctx.argv) > 1 else ctx.session.username
        if not db.get_user(name):
            ctx.errorln(f"groups: '{name}': no such user")
            return 1
        _, gids = db.groups_of(name)
        ctx.writeln(" ".join(db.gname(g) for g in gids))
        return 0


class Useradd(Command):
    name = "useradd"
    synopsis = "useradd [-m] [-s shell] [-u uid] name"
    help_text = ("Create a new user account (root only).\n"
                 "  -m  create the home directory\n"
                 "  -s  login shell\n  -u  numeric user id")

    def run(self, ctx):
        if not self.require_root(ctx):
            return 1
        flags, values, operands = self.parse_flags(ctx.argv[1:],
                                                    valued=("s", "u"))
        if not operands:
            ctx.errorln("useradd: missing username")
            return 1
        name = operands[0]
        try:
            uid = int(values["u"]) if "u" in values else None
            user = ctx.kernel.userdb.add_user(
                name, uid=uid, shell=values.get("s", "/bin/minish"),
                create_home="m" in flags)
        except (UserDBError, ValueError) as e:
            ctx.errorln(f"useradd: {e}")
            return 1
        ctx.kernel.log("auth", f"new user: name={name}, uid={user.uid}")
        return 0


class Userdel(Command):
    name = "userdel"
    synopsis = "userdel [-r] name"
    help_text = "Delete a user account (root only). -r also removes the home dir."

    def run(self, ctx):
        if not self.require_root(ctx):
            return 1
        flags, _, operands = self.parse_flags(ctx.argv[1:])
        if not operands:
            ctx.errorln("userdel: missing username")
            return 1
        try:
            ctx.kernel.userdb.del_user(operands[0], remove_home="r" in flags)
        except UserDBError as e:
            ctx.errorln(f"userdel: {e}")
            return 1
        ctx.kernel.log("auth", f"delete user '{operands[0]}'")
        return 0


class Usermod(Command):
    name = "usermod"
    synopsis = "usermod -aG group user"
    help_text = "Modify a user account (root only). -aG adds to a group."

    def run(self, ctx):
        if not self.require_root(ctx):
            return 1
        flags, values, operands = self.parse_flags(ctx.argv[1:],
                                                    valued=("G",))
        if "G" in values and len(operands) >= 1:
            group = values["G"]
            user = operands[0]
            try:
                ctx.kernel.userdb.add_to_group(user, group)
            except UserDBError as e:
                ctx.errorln(f"usermod: {e}")
                return 1
            return 0
        ctx.errorln("usermod: nothing to do (try: usermod -aG group user)")
        return 1


class Passwd(Command):
    name = "passwd"
    synopsis = "passwd [user]"
    help_text = ("Change a password. A normal user may only change their own; "
                 "root may change any.")

    def run(self, ctx):
        db = ctx.kernel.userdb
        target = ctx.argv[1] if len(ctx.argv) > 1 else ctx.session.username
        if not db.get_user(target):
            ctx.errorln(f"passwd: user '{target}' does not exist")
            return 1
        if not ctx.session.is_root and target != ctx.session.username:
            ctx.errorln("passwd: You may not change the password for another user.")
            return 1

        prompt = ctx.kernel.password_prompt
        if prompt is None:
            # non-interactive fallback: allow "passwd user newpass" for scripting/tests
            if len(ctx.argv) >= 3:
                db.set_password(target, ctx.argv[2])
                ctx.writeln(f"passwd: password updated successfully for {target}")
                return 0
            ctx.errorln("passwd: cannot read password in this context")
            return 1

        # verify current password unless root is changing someone else's
        if not ctx.session.is_root:
            current = prompt("Current password: ")
            if not db.verify(ctx.session.username, current):
                ctx.errorln("passwd: Authentication token manipulation error")
                return 1
        new1 = prompt("New password: ")
        new2 = prompt("Retype new password: ")
        if new1 != new2:
            ctx.errorln("passwd: passwords do not match")
            return 1
        db.set_password(target, new1)
        ctx.kernel.log("auth", f"password changed for user {target}")
        ctx.writeln(f"passwd: password updated successfully for {target}")
        return 0


class Su(Command):
    name = "su"
    synopsis = "su [-|-l] [user]"
    help_text = ("Switch user (default root). '-' or '-l' starts a login shell.\n"
                 "Type 'exit' to return to the previous user.")

    def run(self, ctx):
        args = ctx.argv[1:]
        login = False
        target = None
        for a in args:
            if a in ("-", "-l", "--login"):
                login = True
            elif not a.startswith("-"):
                target = a
        target = target or "root"
        db = ctx.kernel.userdb
        if not db.get_user(target):
            ctx.errorln(f"su: user {target} does not exist")
            return 1

        # root may become anyone without a password
        if not ctx.session.is_root:
            prompt = ctx.kernel.password_prompt
            if prompt is None:
                ctx.errorln("su: cannot read password in this context")
                return 1
            if not ctx.kernel.authenticate(target, prompt("Password: ")):
                ctx.errorln("su: Authentication failure")
                return 1
        ctx.kernel.switch_user(target, login=login)
        return 0


class Users(Command):
    name = "users"
    synopsis = "users"
    help_text = "List all user accounts on the system."

    def run(self, ctx):
        for u in ctx.kernel.userdb.users():
            ctx.writeln(u.name)
        return 0
