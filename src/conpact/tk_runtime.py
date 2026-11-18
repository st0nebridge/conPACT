"""
@module conpact.tk_runtime
@description Lets Tk start inside a virtual environment. Tcl looks for its own
             library (init.tcl) relative to the running interpreter's prefix.
             A venv made on a standalone CPython - the build `uv` installs,
             and so a `uv tool install` of conPACT - has no Tcl library under
             its prefix, so Tk() raises "Can't find a usable init.tcl" and no
             window can open. prepare() points TCL_LIBRARY and TK_LIBRARY at
             the base interpreter's libraries, found by looking, so an upgraded
             interpreter is found too. It changes nothing outside a venv, when
             the user set either variable, or when the base has no Tcl library.
             Call it before the first tk.Tk() of a process.
@input      the process environment; sys.prefix and sys.base_prefix
@output     TCL_LIBRARY / TK_LIBRARY set in that environment when needed
@dependencies stdlib: os, sys, pathlib
"""
import os
import sys
from pathlib import Path


def _newest(lib: Path, stem: str, script: str) -> str | None:
    """The newest lib/<stem>X.Y holding <script>, or None."""
    found = []
    for path in lib.glob(stem + "[0-9]*.[0-9]*"):
        try:
            version = tuple(int(part) for part in path.name[len(stem):].split("."))
        except ValueError:
            continue
        if (path / script).is_file():
            found.append((version, path))
    return str(max(found)[1]) if found else None


def prepare(env=None, prefix: str | None = None, base_prefix: str | None = None) -> None:
    """Point Tcl and Tk at the base interpreter's libraries when in a venv."""
    env = os.environ if env is None else env
    prefix = sys.prefix if prefix is None else prefix
    base_prefix = sys.base_prefix if base_prefix is None else base_prefix
    if os.path.realpath(prefix) == os.path.realpath(base_prefix):
        return
    if env.get("TCL_LIBRARY") or env.get("TK_LIBRARY"):
        return
    lib = Path(base_prefix) / "lib"
    tcl = _newest(lib, "tcl", "init.tcl")
    if tcl is None:
        return
    env["TCL_LIBRARY"] = tcl
    tk = _newest(lib, "tk", "tk.tcl")
    if tk is not None:
        env["TK_LIBRARY"] = tk
