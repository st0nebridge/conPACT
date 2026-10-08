"""
Regression test for CU-20260919-005 (review finding 6).

Only the caller whose delete of the request succeeds may fire. If the delete
fails - the file is locked, or another Stop hook already claimed it - the request
is not handed out. Before this fix a failed delete was ignored and the request
data returned anyway, so the file stayed and fired again at every turn end.
"""
import pathlib

from conpact import compaction


def test_failed_delete_means_no_fire(tmp_path, monkeypatch):
    compaction.request_compaction("sess-a", requests_dir=tmp_path)

    def locked(self, *a, **k):
        raise PermissionError("locked")

    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "unlink", locked)
        assert compaction.consume_request("sess-a", requests_dir=tmp_path) is None
        assert compaction.consume_request("sess-a", requests_dir=tmp_path) is None
    # Once the lock clears, the never-fired request is claimed exactly once.
    assert compaction.consume_request("sess-a", requests_dir=tmp_path) is not None
    assert compaction.consume_request("sess-a", requests_dir=tmp_path) is None


def test_claim_lost_to_another_consumer_means_no_fire(tmp_path, monkeypatch):
    compaction.request_compaction("sess-a", requests_dir=tmp_path)
    real_unlink = pathlib.Path.unlink

    def raced(self, *a, **k):
        real_unlink(self)                       # the other hook's delete wins ...
        raise FileNotFoundError(str(self))      # ... so ours finds nothing to delete

    monkeypatch.setattr(pathlib.Path, "unlink", raced)
    assert compaction.consume_request("sess-a", requests_dir=tmp_path) is None
