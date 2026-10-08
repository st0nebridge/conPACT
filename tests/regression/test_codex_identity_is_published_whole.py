"""
Regression test for CU-20260924-070 (Codex thread identity is published atomically).

The sidecar replaces its active-thread record whole, so an MCP server reading it
never sees it truncated or half written. Contributed by Lance Sandino (pull
request #2 of the public repository); moved here from tests/test_codex_active.py
when it was brought into this history, unchanged but for leaving its class.
"""
from conpact import codex_active


def test_a_reader_never_sees_the_record_half_written(tmp_path,
                                                     monkeypatch):
    assert codex_active.publish(["old"], home=tmp_path) is True
    real_replace = codex_active.os.replace
    observed = []

    def replace(source, destination):
        observed.append(codex_active.read(home=tmp_path))
        real_replace(source, destination)

    monkeypatch.setattr(codex_active.os, "replace", replace)
    assert codex_active.publish(["new"], home=tmp_path) is True
    assert observed[0]["threads"] == ["old"]
    assert codex_active.read(home=tmp_path)["threads"] == ["new"]
