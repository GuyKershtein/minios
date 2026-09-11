"""The apt package-manager command."""

from __future__ import annotations

from ...packages.package_manager import PackageError
from .base import Command


class Apt(Command):
    name = "apt"
    aliases = ("apt-get",)
    synopsis = "apt update|install|remove|search|list|show ..."
    help_text = ("Package manager.\n"
                 "  apt update            refresh the package list\n"
                 "  apt install <pkg>     install a package (root)\n"
                 "  apt remove <pkg>      remove a package (root)\n"
                 "  apt search <term>     search available packages\n"
                 "  apt list [--installed]  list packages\n"
                 "  apt show <pkg>        show package details")

    def run(self, ctx):
        if len(ctx.argv) < 2:
            ctx.errorln(self.synopsis)
            return 1
        sub = ctx.argv[1]
        args = ctx.argv[2:]
        pm = ctx.kernel.pkg
        handler = getattr(self, f"_{sub.replace('-', '_')}", None)
        if handler is None:
            ctx.errorln(f"apt: invalid operation {sub}")
            return 1
        return handler(ctx, pm, args)

    # -- subcommands ------------------------------------------------------
    def _update(self, ctx, pm, args):
        if not self.require_root(ctx):
            return 1
        for line in pm.update():
            ctx.writeln(line)
        return 0

    def _install(self, ctx, pm, args):
        if not self.require_root(ctx):
            return 1
        if not args:
            ctx.errorln("apt install: no package specified")
            return 1
        rc = 0
        for name in args:
            try:
                res = pm.install(name)
            except PackageError as e:
                ctx.errorln(f"E: {e}")
                rc = 1
                continue
            if res["already"]:
                ctx.writeln(f"{name} is already the newest version.")
                continue
            newly = [p for p in res["installed"] if p != name]
            if newly:
                ctx.writeln(f"The following additional packages will be "
                            f"installed:\n  {' '.join(newly)}")
            ctx.writeln(f"The following NEW packages will be installed:\n"
                        f"  {' '.join(res['installed'])}")
            for p in res["installed"]:
                pkg = pm.repo.get(p)
                ctx.writeln(f"Unpacking {p} ({pkg.version}) ...")
                ctx.writeln(f"Setting up {p} ({pkg.version}) ...")
        return rc

    def _remove(self, ctx, pm, args):
        if not self.require_root(ctx):
            return 1
        rc = 0
        for name in args:
            try:
                pm.remove(name)
                ctx.writeln(f"Removing {name} ...")
            except PackageError as e:
                ctx.errorln(f"E: {e}")
                rc = 1
        return rc

    _purge = _remove

    def _search(self, ctx, pm, args):
        if not args:
            ctx.errorln("apt search: no search term")
            return 1
        for p in pm.repo.search(args[0]):
            mark = " [installed]" if pm.is_installed(p.name) else ""
            ctx.writeln(f"{p.name}/{pm.repo.url.split('/')[-1]} {p.version}"
                        f"{mark}")
            ctx.writeln(f"  {p.description}")
        return 0

    def _list(self, ctx, pm, args):
        installed_only = "--installed" in args
        db = pm.installed()
        if installed_only:
            for name in sorted(db):
                ctx.writeln(f"{name}/stable {db[name]['version']} [installed]")
        else:
            for p in pm.repo.all():
                mark = " [installed]" if p.name in db else ""
                ctx.writeln(f"{p.name}/stable {p.version}{mark}")
        return 0

    def _show(self, ctx, pm, args):
        if not args:
            ctx.errorln("apt show: no package specified")
            return 1
        pkg = pm.repo.get(args[0])
        if not pkg:
            ctx.errorln(f"E: Unable to locate package {args[0]}")
            return 1
        ctx.writeln(f"Package: {pkg.name}")
        ctx.writeln(f"Version: {pkg.version}")
        ctx.writeln(f"Section: {pkg.section}")
        ctx.writeln(f"Installed-Size: {pkg.size}")
        ctx.writeln(f"Depends: {', '.join(pkg.depends) if pkg.depends else '(none)'}")
        ctx.writeln(f"Description: {pkg.description}")
        status = "installed" if pm.is_installed(pkg.name) else "not installed"
        ctx.writeln(f"Status: {status}")
        return 0
