"""
@module tests.test_codex_sidecar
@description The sidecar that stands in ChatGPT Desktop's app-server stdio path:
             which invocations it proxies and which it never touches, the
             framing that decides whether a line is the desktop's or a reply to
             something we injected, the token that guards the control channel,
             and the promise that the desktop's own stream comes through byte for
             byte. This is the logic that used to be C and could only be reasoned
             about; being Python it is measured here, on any platform.
@input      conpact.codex_sidecar, against fake streams and sockets
@output     assertions on argument classification, line lifting, authentication
            and stream fidelity
@dependencies conpact.codex_sidecar; stdlib: json, threading
"""
import json
import os
import threading

import pytest

from conpact import codex_sidecar as sc

TAG = "conpact-4242-"


class FakeConn:
    """A control client: what it was sent, and what it will say."""

    def __init__(self, says=(), fail_on_send=False):
        self.says, self.sent, self.closed = list(says), [], False
        self.fail_on_send = fail_on_send
        self.delivered = threading.Event()

    def recv(self, _n):
        return self.says.pop(0) if self.says else b""

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        if self.fail_on_send:
            raise OSError("client went away")
        self.sent.append(data)
        self.delivered.set()

    def close(self):
        self.closed = True


class FakeStdin:
    """The child's stdin: everything written to it, in order."""

    def __init__(self, fail=False):
        self.written, self.closed, self.fail = [], False, fail

    def write(self, data):
        if self.fail:
            raise OSError("the app-server is gone")
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def joined(self):
        return b"".join(self.written)


def reader(*chunks):
    """A read() that hands back each chunk once, then end-of-stream."""
    queue = list(chunks)
    return lambda _n: queue.pop(0) if queue else b""


class TestWhichInvocationsAreProxied:
    @pytest.mark.parametrize("argv", [
        ["app-server"],
        ["app-server", "--experimental"],
        ["--verbose", "app-server"]])
    def test_the_desktops_stdio_app_server_is_proxied(self, argv):
        assert sc.is_desktop_app_server(argv) is True

    @pytest.mark.parametrize("argv", [
        [],
        ["exec", "--prompt", "hi"],
        ["app-server", "proxy"],
        ["app-server", "daemon", "start"],
        ["app-server", "generate-ts"],
        ["app-server", "--listen", "ws://127.0.0.1:9000"],
        ["app-server", "--listen=ws://127.0.0.1:9000"],
        ["app-server", "--stdio"]])
    def test_everything_else_is_passed_straight_through(self, argv):
        assert sc.is_desktop_app_server(argv) is False

    def test_a_listener_of_our_own_is_never_proxied(self):
        """conPACT's own app-server is started with --listen; proxying it
        would have the sidecar stand in front of itself."""
        from conpact import codex_appserver
        argv = list(codex_appserver.listen_args("127.0.0.1", 9000, "abc"))
        assert sc.is_desktop_app_server(argv) is False


class TestLiftingOurRepliesOut:
    def test_a_line_with_our_tag_is_ours_and_loses_its_newline(self):
        lifter = sc.Lifter(TAG)
        body = json.dumps({"id": TAG + "x", "result": {}})
        assert lifter.feed(body.encode() + b"\n") == [(True, body.encode())]

    def test_every_other_line_is_the_desktops_and_keeps_its_newline(self):
        lifter = sc.Lifter(TAG)
        assert lifter.feed(b'{"id":"theirs"}\n') == [(False, b'{"id":"theirs"}\n')]

    def test_a_line_split_across_reads_is_held_until_it_is_whole(self):
        lifter = sc.Lifter(TAG)
        assert lifter.feed(b'{"id":"the') == []
        assert lifter.feed(b'irs"}\n') == [(False, b'{"id":"theirs"}\n')]

    def test_several_lines_in_one_read_are_each_placed(self):
        lifter = sc.Lifter(TAG)
        got = lifter.feed(b'{"a":1}\n{"id":"' + TAG.encode() + b'9"}\n{"b":2}\n')
        assert [ours for ours, _ in got] == [False, True, False]

    def test_the_tag_matches_whatever_spacing_the_app_server_writes(self):
        """json.dumps writes `"id": "..."`, the shim wrote `"id":"..."`; the tag
        is the value's prefix so neither spacing can miss."""
        lifter = sc.Lifter(TAG)
        spaced = json.dumps({"id": TAG + "x", "result": {}}).encode()
        assert lifter.feed(spaced + b"\n")[0][0] is True

    def test_what_never_got_a_newline_is_still_handed_over_at_the_end(self):
        lifter = sc.Lifter(TAG)
        lifter.feed(b"half a line")
        assert lifter.rest() == b"half a line"
        assert lifter.rest() == b""

    def test_the_desktops_stream_is_reassembled_byte_for_byte(self):
        lifter = sc.Lifter(TAG)
        original = b'{"a":1}\n{"b":[2,3]}\n{"c":"\xc3\xa9"}\n'
        out = b""
        for at in range(0, len(original), 5):
            for ours, line in lifter.feed(original[at:at + 5]):
                assert ours is False
                out += line
        assert out + lifter.rest() == original


class TestTheControlChannelIsGuarded:
    def test_the_right_token_opens_it_and_what_follows_is_kept(self):
        assert sc.greet("secret", b"secret\n{\"id\":1}\n") == b'{"id":1}\n'

    def test_a_wrong_token_is_refused_and_nothing_it_sent_is_returned(self):
        assert sc.greet("secret", b"guess\n{\"id\":1}\n") is None

    def test_a_client_that_sends_no_line_is_refused(self):
        assert sc.greet("secret", b"secret") is None

    def test_an_empty_opening_is_refused(self):
        assert sc.greet("secret", b"") is None

    def test_a_token_with_surrounding_whitespace_still_opens_it(self):
        assert sc.greet("secret", b"  secret \n") == b""

    def test_an_unauthenticated_client_never_reaches_the_app_server(self):
        """The refusal is what matters: an unknown caller must not be able to
        write a single byte into the desktop's app-server."""
        stdin = FakeStdin()
        server = FakeServer([FakeConn(says=[b"wrong\n{\"evil\":1}\n"])])
        sc.serve_control(server, sc.Control(), stdin, threading.Lock(), "secret")
        assert stdin.written == []


class FakeServer:
    """An accept() that hands over each connection once, then stops the loop."""

    def __init__(self, conns):
        self.conns = list(conns)

    def accept(self):
        if not self.conns:
            raise OSError("closed")
        return self.conns.pop(0), ("127.0.0.1", 1)


class TestServingTheControlChannel:
    def test_invalid_utf8_does_not_stop_the_listener(self):
        stdin = FakeStdin()
        bad = FakeConn(says=[b"\xff\n"])
        good = FakeConn(says=[b"sec", b"ret\n{\"id\":9}\n"])
        sc.serve_control(FakeServer([bad, good]), sc.Control(), stdin,
                         threading.Lock(), "secret")
        assert bad.closed and good.closed
        assert stdin.joined() == b'{"id":9}\n'

    def test_what_an_authenticated_client_writes_reaches_the_app_server(self):
        stdin = FakeStdin()
        conn = FakeConn(says=[b"secret\n{\"id\":1}\n", b"{\"id\":2}\n"])
        sc.serve_control(FakeServer([conn]), sc.Control(), stdin, threading.Lock(), "secret")
        assert stdin.joined() == b'{"id":1}\n{"id":2}\n'

    def test_a_client_that_goes_away_is_dropped_and_the_next_is_served(self):
        stdin = FakeStdin()
        first = FakeConn(says=[b"secret\n"])
        second = FakeConn(says=[b"secret\n{\"id\":9}\n"])
        sc.serve_control(FakeServer([first, second]), sc.Control(), stdin,
                         threading.Lock(), "secret")
        assert first.closed is True
        assert stdin.joined() == b'{"id":9}\n'

    def test_a_refused_client_does_not_become_the_one_replies_go_to(self):
        control = sc.Control()
        sc.serve_control(FakeServer([FakeConn(says=[b"wrong\n"])]), control,
                         FakeStdin(), threading.Lock(), "secret")
        assert control.client is None

    def test_a_client_that_never_authenticates_times_out_and_the_next_is_served(self):
        class TimeoutConn(FakeConn):
            def recv(self, _):
                self.waited = self.timeout
                raise TimeoutError('no greeting')
        stdin, slow = FakeStdin(), TimeoutConn()
        next_client = FakeConn(says=[b'secret\n{"id":"next"}\n'])
        sc.serve_control(FakeServer([slow, next_client]), sc.Control(), stdin,
                         threading.Lock(), 'secret')
        assert 0 < slow.waited <= 5
        assert slow.closed
        assert stdin.joined() == b'{"id":"next"}\n'


class TestHandingRepliesBack:
    def test_a_reply_goes_to_the_client_with_its_newline_restored(self):
        control, conn = sc.Control(), FakeConn()
        control.adopt(conn)
        control.give(b'{"id":"x"}')
        assert conn.delivered.wait(1)
        control.release(conn)
        assert conn.sent == [b'{"id":"x"}\n']

    def test_a_reply_with_no_client_is_simply_dropped(self):
        sc.Control().give(b'{"id":"x"}')        # must not raise

    def test_a_client_that_will_not_take_it_is_dropped(self):
        control, conn = sc.Control(), FakeConn(fail_on_send=True)
        control.adopt(conn)
        control.give(b'{"id":"x"}')
        control.sender.join(1)
        assert control.client is None and conn.closed is True

    def test_adopting_a_second_client_closes_the_first(self):
        control, first = sc.Control(), FakeConn()
        control.adopt(first)
        control.adopt(FakeConn())
        assert first.closed is True

    def test_releasing_a_superseded_client_preserves_the_current_client(self):
        control, old, current = sc.Control(), FakeConn(), FakeConn()
        control.adopt(old)
        control.adopt(current)
        control.release(old)
        assert old.closed and control.client is current

    def test_a_send_timeout_drops_the_control_client(self):
        class TimedOut(FakeConn):
            def sendall(self, _):
                raise TimeoutError('client stopped reading')
        control, conn = sc.Control(), TimedOut()
        control.adopt(conn)
        control.give(b'{"id":"reply"}')
        control.sender.join(1)
        assert control.client is None and conn.closed

    def test_a_close_error_does_not_prevent_adopting_a_new_client(self):
        class BrokenClose(FakeConn):
            def close(self):
                raise OSError('already closed')
        control, current = sc.Control(), FakeConn()
        control.adopt(BrokenClose())
        control.adopt(current)
        control.give(b'{"id":"reply"}')
        assert current.delivered.wait(1)
        control.release(current)
        assert current.sent == [b'{"id":"reply"}\n']


class TestThePumps:
    def test_the_desktop_reaches_the_app_server_byte_for_byte(self):
        stdin = FakeStdin()
        sc.pump_to_child(reader(b'{"a":1}\n', b'{"b":'), stdin, threading.Lock())
        assert stdin.joined() == b'{"a":1}\n{"b":'
        assert stdin.closed is True          # the desktop closed its side

    def test_an_app_server_that_dies_mid_write_does_not_raise(self):
        sc.pump_to_child(reader(b"anything"), FakeStdin(fail=True), threading.Lock())

    def test_the_app_servers_stream_reaches_the_desktop_minus_our_replies(self):
        written, control = [], sc.Control()
        conn = FakeConn()
        control.adopt(conn)
        mine = json.dumps({"id": TAG + "1", "result": {"ok": True}}).encode()
        sc.pump_to_desktop(reader(b'{"theirs":1}\n' + mine + b'\n{"theirs":2}\n'),
                           written.append, sc.Lifter(TAG), control)
        assert b"".join(written) == b'{"theirs":1}\n{"theirs":2}\n'
        assert conn.delivered.wait(1)
        control.release(conn)
        assert conn.sent == [mine + b"\n"]

    def test_a_trailing_partial_line_is_still_delivered(self):
        written = []
        sc.pump_to_desktop(reader(b'{"a":1}\n{"partial"'), written.append,
                           sc.Lifter(TAG), sc.Control())
        assert b"".join(written) == b'{"a":1}\n{"partial"'

    def test_method_changes_are_published_while_the_calling_thread_stays_the_same(self):
        from conpact import codex_turns
        turns, snapshots = codex_turns.Turns(), []
        messages = [json.dumps({'method': 'item/started', 'params': {
            'threadId': 't', 'item': {'id': item, 'type': 'mcpToolCall',
                                     'server': 'conpact', 'tool': method}}}).encode() + b'\n'
                    for item, method in [('a', 'compaction_status'), ('b', 'queue_compaction')]]
        sc.pump_to_desktop(reader(*messages), lambda _: None, sc.Lifter(TAG), sc.Control(),
                           turns=turns, publish=lambda *_: snapshots.append(turns.calling_tools()))
        assert snapshots == [{'compaction_status': ['t']},
                             {'compaction_status': ['t'], 'queue_compaction': ['t']}]

    def test_a_failed_publisher_does_not_stop_desktop_replies(self):
        from conpact import codex_turns
        written = []
        def failed(*_):
            raise OSError('record locked')
        sc.pump_to_desktop(reader(b'{"method":"turn/started","params":{"threadId":"t"}}\n',
                                  b'{"id":"desktop","result":{}}\n'), written.append,
                           sc.Lifter(TAG), sc.Control(), turns=codex_turns.Turns(), publish=failed)
        assert len(written) == 2

    def test_a_child_write_failure_with_a_complete_line_is_bounded(self):
        stdin = FakeStdin(fail=True)
        sc.pump_to_child(reader(b'{"id":"desktop"}\n'), stdin, threading.Lock())
        assert stdin.written == []

    def test_a_closed_desktop_output_stops_the_reader(self):
        reads = []
        def read(_):
            reads.append(True)
            return b'{"id":"desktop"}\n'
        sc.pump_to_desktop(read, lambda _: 0, sc.Lifter(TAG), sc.Control())
        assert reads == [True]


class TestUnproxiedLaunch:
    def test_non_app_server_commands_keep_their_arguments_and_environment(self, monkeypatch):
        from types import SimpleNamespace
        called = []
        monkeypatch.setattr(sc, 'os', SimpleNamespace(environ={}, name='nt'))
        monkeypatch.setattr(sc.subprocess, 'call', lambda argv, **kw: called.append((argv, kw)) or 17)
        assert sc.passthrough('real-codex', ['--version'], environ={'KEEP': 'yes'}) == 17
        assert called == [(['real-codex', '--version'],
                           {'env': {'KEEP': 'yes', 'CODEX_CLI_PATH': 'real-codex'}})]

    def test_posix_exec_failure_falls_back_to_the_same_command(self, monkeypatch):
        from types import SimpleNamespace
        called = []
        def missing(*args):
            raise OSError('exec failed')
        monkeypatch.setattr(sc, 'os', SimpleNamespace(environ={}, name='posix', execve=missing))
        monkeypatch.setattr(sc.subprocess, 'call', lambda argv, **kw: called.append(argv) or 18)
        assert sc.passthrough('real-codex', ['--version'], environ={}) == 18
        assert called == [['real-codex', '--version']]

    def test_an_unavailable_control_socket_leaves_proxying_available(self, monkeypatch):
        from types import SimpleNamespace
        def unavailable(*_):
            raise OSError('loopback unavailable')
        monkeypatch.setattr(sc, 'socket', SimpleNamespace(socket=unavailable, AF_INET=2, SOCK_STREAM=1))
        assert sc.open_control() is None


class TestProxyWiring:
    def test_the_proxy_publishes_the_child_owner_and_preserves_desktop_traffic(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from conpact import codex_active
        child = SimpleNamespace(pid=123, stdin=FakeStdin(), stdout=SimpleNamespace(read=reader(
            b'{"method":"item/started","params":{"threadId":"t","item":'
            b'{"id":"i","type":"mcpToolCall","server":"conpact","tool":"queue_compaction"}}}\n')),
            wait=lambda: 0)
        launched = []
        monkeypatch.setattr(sc.subprocess, 'Popen', lambda argv, **kw: launched.append((argv, kw)) or child)
        server = FakeServer([])
        server.getsockname = lambda: ('127.0.0.1', 5555)
        closed = []
        server.close = lambda: closed.append(True)
        monkeypatch.setattr(sc, 'open_control', lambda: server)
        monkeypatch.setattr(sc.codex_sidecar_log, 'open_tap', lambda: None)
        snapshots, transformed = [], []
        def transport_snapshot(**kwargs):
            snapshots.append(kwargs)
            def transform(line):
                transformed.append(line)
                return line
            return transform
        monkeypatch.setattr(sc.codex_transport, 'load', transport_snapshot)

        class SynchronousThread:
            def __init__(self, target, args, daemon):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

        monkeypatch.setattr(sc, 'threading', SimpleNamespace(Lock=threading.Lock, Thread=SynchronousThread))
        written = []
        assert sc.proxy('real-codex', ['app-server'], home=tmp_path,
                        read_in=reader(b'{"id":"desktop","method":"account/read"}\n'),
                        write_out=written.append) == 0
        assert child.stdin.joined() == b'{"id":"desktop","method":"account/read"}\n'
        assert snapshots == [{'args': ['app-server']}]
        assert transformed == [child.stdin.joined()]
        assert json.loads(b''.join(written))['method'] == 'item/started'
        assert launched[0][1]['env']['CODEX_CLI_PATH'] == 'real-codex'
        assert codex_active.sole_thread(home=tmp_path, parent_pid=123,
                                        tool_name='queue_compaction') == ('t', None)
        assert closed == [True]

    def test_turn_end_worker_carries_only_its_own_app_server(self):
        seen = []
        sc.arm_on_turn_end("t-1", environ={sc.codex_inject.OWNER_ENV: "999"}, owner_pid=123,
                           spawner=lambda argv, env: seen.append(env) or 1)
        assert seen[0][sc.codex_inject.OWNER_ENV] == "123"

    def test_owned_record_is_written_atomically_and_retains_private_permissions(self, tmp_path, monkeypatch):
        sc.write_record(5555, "test-token", 99, TAG, home=tmp_path, parent_pid=123)
        folder = tmp_path / ".conpact"
        owner = json.loads((folder / sc.codex_inject.OWNERS / "123.json").read_text())
        global_record = json.loads((folder / sc.RECORD).read_text())
        assert owner == global_record and owner["parent_pid"] == 123
        def failed_replace(*a):
            raise OSError("record busy")
        monkeypatch.setattr(sc.os, "replace", failed_replace)
        with pytest.raises(OSError, match="record busy"):
            sc.write_record(6666, "replacement", 99, TAG, home=tmp_path, parent_pid=123)
        assert json.loads((folder / sc.codex_inject.OWNERS / "123.json").read_text()) == owner
        assert list(folder.rglob("*.tmp")) == []


class TestFindingTheRealCodex:
    """The pin, then the marker, then whatever is installed now - and each of
    the first two only while it still names a file. Codex prunes old builds, so
    a name written at install goes stale by itself."""

    def _install(self, root, name, mtime=1_789_811_209.0):
        folder = root / "OpenAI" / "Codex" / "bin" / name
        folder.mkdir(parents=True)
        exe = folder / "codex.exe"
        exe.write_text("", encoding="utf-8")
        os.utime(exe, (mtime, mtime))
        return exe

    def test_the_environment_names_it_outright(self, tmp_path):
        real = tmp_path / "codex.exe"
        real.write_text("", encoding="utf-8")
        assert sc.real_codex({"CONPACT_CODEX_REAL": str(real)}) == str(real)

    def test_otherwise_the_marker_beside_the_shim_names_it(self, tmp_path):
        real = tmp_path / "codex.exe"
        real.write_text("", encoding="utf-8")
        (tmp_path / "real-codex.txt").write_text(str(real), encoding="utf-8")
        assert sc.real_codex({"LOCALAPPDATA": str(tmp_path / "installs")},
                             beside=tmp_path) == str(real)

    def test_a_pin_naming_a_deleted_build_falls_through_to_the_marker(self, tmp_path):
        real = tmp_path / "codex.exe"
        real.write_text("", encoding="utf-8")
        (tmp_path / "real-codex.txt").write_text(str(real), encoding="utf-8")
        gone = str(tmp_path / "pruned" / "codex.exe")
        assert sc.real_codex({"CONPACT_CODEX_REAL": gone,
                              "LOCALAPPDATA": str(tmp_path / "installs")},
                             beside=tmp_path) == str(real)

    def test_a_marker_naming_a_deleted_build_falls_through_to_what_is_installed(
            self, tmp_path):
        """The incident of 2026-09-22: Codex deleted the build the marker named,
        and a shim that trusted it would have left the desktop with no codex."""
        newest = self._install(tmp_path, "aaaaaaaaaaaaaaaa")
        (tmp_path / "real-codex.txt").write_text(
            str(tmp_path / "OpenAI" / "Codex" / "bin" / "pruned" / "codex.exe"),
            encoding="utf-8")

        found = sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path)

        assert found == str(newest), "a pruned build must not take the desktop down"

    def test_the_fallback_does_not_resolve_back_through_the_shim(self, tmp_path):
        """CODEX_CLI_PATH points at us; resolving it would find the shim."""
        newest = self._install(tmp_path, "aaaaaaaaaaaaaaaa")
        env = {"LOCALAPPDATA": str(tmp_path),
               "CODEX_CLI_PATH": str(tmp_path / "codex_sidecar.exe")}
        assert sc.real_codex(env, beside=tmp_path) == str(newest)

    def test_no_marker_and_no_environment_is_nothing(self, tmp_path):
        assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) is None

    def test_an_empty_marker_is_nothing_rather_than_an_empty_command(self, tmp_path):
        (tmp_path / "real-codex.txt").write_text("   ", encoding="utf-8")
        assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) is None

    def test_nothing_anywhere_and_nothing_installed_is_still_nothing(self, tmp_path):
        assert sc.real_codex({"LOCALAPPDATA": str(tmp_path)}, beside=tmp_path) is None

    def test_the_launcher_may_name_the_folder_the_marker_is_in(self, tmp_path):
        assert sc.shim_dir({"CONPACT_SIDECAR_DIR": str(tmp_path)}) == tmp_path

    def test_without_a_real_codex_it_refuses_rather_than_running_nothing(self, monkeypatch):
        monkeypatch.setattr(sc, "real_codex", lambda: None)
        assert sc.main(["app-server"]) == 1


class TestTheRecordItLeaves:
    def test_it_names_where_to_reach_it_what_to_say_and_what_its_replies_carry(
            self, tmp_path):
        sc.write_record(51234, "s3cret", 4242, TAG, home=tmp_path)
        written = json.loads(sc.record_path(tmp_path).read_text(encoding="utf-8"))
        assert written == {"address": "127.0.0.1:51234", "token": "s3cret",
                           "pid": 4242, "tag": TAG}

    def test_it_is_written_even_when_dot_claude_does_not_exist_yet(self, tmp_path):
        """A machine may run ChatGPT Desktop and not Claude; the record's folder
        is created rather than assumed."""
        assert (tmp_path / ".claude").exists() is False
        sc.write_record(1, "t", 2, TAG, home=tmp_path)
        assert sc.record_path(tmp_path).is_file()

    def test_the_tag_is_the_pid_so_two_sidecars_never_claim_each_others_replies(self):
        assert sc.tag_for(1) != sc.tag_for(2)
        assert sc.tag_for(4242) == TAG

    def test_the_record_reads_back_through_the_client(self, tmp_path, monkeypatch):
        """The two halves agree on the shape, rather than each being right alone."""
        from conpact import codex_inject, compaction
        monkeypatch.setattr(compaction, "STATE_DIR", tmp_path / ".conpact")
        sc.write_record(51234, "s3cret", 4242, TAG, home=tmp_path)
        assert codex_inject.read_record() == {
            "address": "127.0.0.1:51234", "host": "127.0.0.1", "port": 51234,
            "token": "s3cret", "tag": TAG, "pid": 4242}


class TestEveryByteIsWritten:
    """`os.write` and an unbuffered file object may take fewer bytes than they
    are offered and report how many. Discarding that number truncates the
    message, and a truncated JSON-RPC line is not a slow reply - it is a broken
    one, which is what a desktop failing to load its account panel looks like."""

    def test_a_writer_that_takes_a_little_at_a_time_still_gets_it_all(self):
        got = bytearray()

        def dribble(data):
            got.extend(data[:7])
            return min(7, len(data))

        assert sc.write_all(dribble, b"x" * 100) is True
        assert bytes(got) == b"x" * 100

    def test_a_writer_that_reports_nothing_is_taken_at_its_word(self):
        """A buffered file object returns None and writes everything."""
        got = []
        assert sc.write_all(lambda data: got.append(data), b"abc") is True
        assert b"".join(got) == b"abc"

    def test_a_writer_that_takes_nothing_is_a_failure_not_a_loop(self):
        assert sc.write_all(lambda data: 0, b"abc") is False

    def test_a_writer_that_fails_is_reported(self):
        def broken(data):
            raise OSError("pipe closed")
        assert sc.write_all(broken, b"abc") is False

    def test_the_desktops_stream_survives_a_dribbling_pipe(self):
        """End to end: a partial-writing sink must still receive every byte."""
        got = bytearray()

        def dribble(data):
            got.extend(data[:5])
            return min(5, len(data))

        original = b'{"a":1}\n{"b":2}\n'
        sc.pump_to_desktop(reader(original), dribble, sc.Lifter(TAG), sc.Control())
        assert bytes(got) == original


class TestArmingWhenATurnEnds:
    """The sidecar is the turn-end hook Codex does not offer. The rule that
    matters: the desktop's stream is never held up, slowed or broken for it."""

    END = b'{"method":"turn/completed","params":{"threadId":"t-7"}}\n'

    def _pump(self, lines, arm, turns=None):
        from conpact import codex_turns
        chunks = list(lines) + [b""]
        written = []
        sc.pump_to_desktop(lambda _n: chunks.pop(0), written.append,
                           sc.Lifter(TAG), sc.Control(),
                           turns=turns or codex_turns.Turns(), arm=arm)
        return written

    def test_a_turn_ending_arms_that_thread(self):
        armed = []
        self._pump([self.END], armed.append)
        assert armed == ["t-7"]

    def test_the_desktop_still_gets_the_notification(self):
        """We watch the stream; we do not consume from it."""
        written = self._pump([self.END], lambda _t: None)
        assert b"".join(written) == self.END

    def test_ordinary_traffic_arms_nothing(self):
        armed = []
        self._pump([b'{"id":"1","result":{}}\n{"method":"turn/started","params":{}}\n'],
                   armed.append)
        assert armed == []

    def test_an_arming_that_raises_does_not_break_the_stream(self):
        def boom(_thread):
            raise RuntimeError("no python")
        written = self._pump([self.END, b'{"id":"2","result":{}}\n'], boom)
        assert b'"id":"2"' in b"".join(written), "the desktop's next reply still arrived"

    def test_a_burst_arms_once(self):
        armed = []
        self._pump([self.END, self.END, self.END], armed.append)
        assert armed == ["t-7"]


class TestWhatTheArmingIsStartedWith:
    def test_it_is_detached_and_names_the_thread(self):
        seen = {}
        def spawner(argv, env=None):
            seen["argv"], seen["env"] = argv, env
            return 4242
        assert sc.arm_on_turn_end("t-9", spawner=spawner, environ={}) == 4242
        assert seen["argv"][1:5] == ["-m", "conpact.codex_arming", "--thread", "t-9"]
        assert seen["argv"][5] == "--ended-at-ns"
        assert int(seen["argv"][6]) > 0

    def test_the_arming_must_not_re_enter_the_shim(self):
        """CODEX_CLI_PATH names the shim; a child that inherited it would find
        the interposer when it went looking for codex."""
        seen = {}
        def spawner(argv, env=None):
            seen["env"] = env
            return 1
        sc.arm_on_turn_end("t", spawner=spawner,
                           environ={"CODEX_CLI_PATH": r"C:\shim.exe"})
        assert "CODEX_CLI_PATH" not in seen["env"]

    def test_it_puts_the_package_on_the_path(self):
        seen = {}
        sc.arm_on_turn_end("t", spawner=lambda argv, env=None: seen.update(env=env) or 1,
                           environ={})
        assert seen["env"]["PYTHONPATH"].endswith("src")

    def test_a_spawn_that_fails_is_swallowed(self):
        def boom(argv, env=None):
            raise OSError("no interpreter")
        assert sc.arm_on_turn_end("t", spawner=boom, environ={}) is None
