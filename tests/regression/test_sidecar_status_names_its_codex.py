"""
Regression test for CU-20260924-071 (sidecar status shows which Codex build it will run).

`tools/codex_sidecar.py status` names the recorded marker, newest installed build,
and next-launch selection. Contributed by Lance Sandino
(pull request #2 of the public repository); moved here from
tests/test_codex_sidecar_tool.py when it was brought into this history.
"""
from tools import codex_sidecar


def test_status_names_the_pinned_and_newest_codex(monkeypatch, capsys):
    monkeypatch.setattr(codex_sidecar.install, "status", lambda: {
        "platform": "macos",
        "built": True,
        "exe": "/shim",
        "marker_written": True,
        "env_value": "/shim",
        "env_points_at_shim": True,
        "sidecar_running": True,
        "installed": True,
        "codex_pinned": "/Applications/Old.app/codex",
        "codex_newest": "/Applications/New.app/codex",
        "codex_is_newest": False,
        "codex_selected": "/Applications/New.app/codex",
        "codex_selection": "automatic",
    })

    assert codex_sidecar.main(["status"]) == 0
    shown = capsys.readouterr().out
    assert "codex marker    /Applications/Old.app/codex" in shown
    assert "codex newest    /Applications/New.app/codex" in shown
    assert "marker newest   no" in shown
    assert "codex selected  /Applications/New.app/codex" in shown
    assert "selection       automatic (next launch)" in shown
