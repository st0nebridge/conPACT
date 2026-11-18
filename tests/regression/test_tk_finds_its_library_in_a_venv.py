"""
@module tests.regression.test_tk_finds_its_library_in_a_venv
@description Regression test for CU-20261117-130. Run from a virtual environment
             made on a standalone CPython (a `uv tool install`), Tcl looks for
             init.tcl beside the venv's prefix, finds none, and Tk() raises
             "Can't find a usable init.tcl", so the idle toast never shows.
             tk_runtime.prepare points Tcl and Tk at the base interpreter's
             libraries in that case and leaves every other case alone.
@input      conpact.tk_runtime
@output     assertions on the TCL_LIBRARY / TK_LIBRARY it sets or leaves alone
@dependencies conpact.tk_runtime; stdlib: pathlib
"""
from conpact import tk_runtime


def _base(tmp_path, tcl="tcl8.6", tk="tk8.6"):
    base = tmp_path / "base"
    (base / "lib" / tcl).mkdir(parents=True)
    (base / "lib" / tcl / "init.tcl").write_text("", encoding="utf-8")
    (base / "lib" / tk).mkdir(parents=True)
    (base / "lib" / tk / "tk.tcl").write_text("", encoding="utf-8")
    return base


def test_a_venv_is_pointed_at_the_base_libraries(tmp_path):
    base = _base(tmp_path)
    env = {}
    tk_runtime.prepare(env, prefix=str(tmp_path / "venv"), base_prefix=str(base))
    assert env == {"TCL_LIBRARY": str(base / "lib" / "tcl8.6"),
                   "TK_LIBRARY": str(base / "lib" / "tk8.6")}


def test_the_newest_tcl_with_an_init_script_is_chosen(tmp_path):
    base = _base(tmp_path, tcl="tcl9.0", tk="tk9.0")
    (base / "lib" / "tcl8").mkdir()                       # a package dir, no init.tcl
    env = {}
    tk_runtime.prepare(env, prefix=str(tmp_path / "venv"), base_prefix=str(base))
    assert env["TCL_LIBRARY"] == str(base / "lib" / "tcl9.0")
    assert env["TK_LIBRARY"] == str(base / "lib" / "tk9.0")


def test_outside_a_venv_nothing_is_set(tmp_path):
    base = _base(tmp_path)
    env = {}
    tk_runtime.prepare(env, prefix=str(base), base_prefix=str(base))
    assert env == {}


def test_a_value_the_user_set_is_kept(tmp_path):
    base = _base(tmp_path)
    env = {"TCL_LIBRARY": "/mine/tcl", "TK_LIBRARY": "/mine/tk"}
    tk_runtime.prepare(env, prefix=str(tmp_path / "venv"), base_prefix=str(base))
    assert env == {"TCL_LIBRARY": "/mine/tcl", "TK_LIBRARY": "/mine/tk"}


def test_a_base_without_tcl_sets_nothing(tmp_path):
    (tmp_path / "base" / "lib").mkdir(parents=True)
    env = {}
    tk_runtime.prepare(env, prefix=str(tmp_path / "venv"), base_prefix=str(tmp_path / "base"))
    assert env == {}
