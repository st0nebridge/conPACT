"""Only verified transparent launchers may stand between MCP and its owner."""
import pytest
import sys

from conpact import runtime_parent as rp

PYTHON = 'C:/venv/Scripts/python.exe'
ENTRY = 'C:/venv/Scripts/conpact-mcp.exe'


def row(pid, parent, exe, command):
    return dict(ProcessId=pid, ParentProcessId=parent, ExecutablePath=exe, CommandLine=command,
                CreationDate='2026-01-01T00:00:00')


def resolve(rows):
    owners = [row(1, 0, 'C:/app.exe', 'C:/app.exe'), row(9, 0, 'C:/app.exe', 'C:/app.exe')]
    return rp.resolve(owners + rows, 3, 2, PYTHON, ENTRY)


def test_venv_redirector_is_transparent():
    rows = [row(3, 2, 'C:/base/python.exe', '"C:/base/python.exe" -m conpact.mcp_server'),
            row(2, 1, PYTHON, f'"{PYTHON}" -m conpact.mcp_server')]
    assert resolve(rows) == 1


def test_console_entrypoint_is_transparent():
    rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{ENTRY}"'),
            row(2, 1, ENTRY, f'"{ENTRY}"')]
    assert resolve(rows) == 1


def test_an_unquoted_launcher_command_is_read_like_a_quoted_one():
    rows = [row(3, 2, 'C:/base/python.exe', 'C:/base/python.exe -m conpact.mcp_server'),
            row(2, 1, PYTHON, f'{PYTHON} -m conpact.mcp_server')]
    assert resolve(rows) == 1


def test_rows_that_are_not_process_records_are_ignored():
    rows = [None, 'ProcessId', ['ProcessId'], {'ParentProcessId': 2},
            row(3, 2, 'C:/base/python.exe', '"C:/base/python.exe" -m conpact.mcp_server'),
            row(2, 1, PYTHON, f'"{PYTHON}" -m conpact.mcp_server')]
    assert resolve(rows) == 1


def test_no_more_than_two_wrappers_are_unwrapped():
    rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{ENTRY}" --serve'),
            row(2, 1, PYTHON, f'"{PYTHON}" "{ENTRY}" --serve'),
            row(1, 9, ENTRY, f'"{ENTRY}" --serve'),
            row(9, 8, PYTHON, f'"{PYTHON}" --serve'),
            row(8, 0, 'C:/app.exe', 'C:/app.exe')]
    assert rp.resolve(rows, 3, 2, PYTHON, ENTRY) == 9


def test_an_edge_without_evidence_is_false():
    child, parent = row(3, 2, 'C:/a.exe', 'C:/a.exe'), row(2, 1, 'C:/b.exe', 'C:/b.exe')
    assert rp._edge(child, parent) is True
    assert rp._edge(None, parent) is False
    assert rp._edge(child, row(4, 1, 'C:/b.exe', 'C:/b.exe')) is False


@pytest.mark.parametrize('exe,command', [
    (PYTHON, f'"{PYTHON}" other_script.py'),
    ('C:/foreign/python.exe', '"C:/foreign/python.exe" -m conpact.mcp_server'),
    (ENTRY, f'"{ENTRY}" --different'),
    (ENTRY, f'"{ENTRY}" conpact.mcp_server'),
    ('C:/shell.exe', 'C:/shell.exe'),
])
def test_nontransparent_parent_is_never_skipped(exe, command):
    assert resolve([row(3, 2, 'C:/base/python.exe', 'C:/base/python.exe -m conpact.mcp_server'),
                    row(2, 1, exe, command)]) == 2


def test_missing_observation_and_cycle_refuse_to_skip():
    assert resolve([]) == 2
    assert resolve([row(3, 2, PYTHON, f'{PYTHON} -m conpact.mcp_server'),
                    row(2, 3, PYTHON, f'{PYTHON} -m conpact.mcp_server')]) == 2


def test_platform_and_reader_failures_preserve_direct_parent(monkeypatch):
    monkeypatch.setattr(rp.sys, 'platform', 'linux')
    assert rp.owner(7, reader=lambda: pytest.fail('Windows only')) == 7
    monkeypatch.setattr(rp.sys, 'platform', 'win32')
    assert rp.owner(7, reader=lambda: []) == 7


def test_both_wrappers_are_followed_in_order():
    rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{ENTRY}"'),
            row(2, 1, PYTHON, f'"{PYTHON}" "{ENTRY}"'),
            row(1, 9, ENTRY, f'"{ENTRY}"')]
    assert resolve(rows) == 9


@pytest.mark.parametrize('alter', [
    {'ParentProcessId': 0}, {'ParentProcessId': None},
    {'ExecutablePath': None}, {'CommandLine': ''},
    {'CreationDate': '2099-01-01'}, {'CreationDate': None}, {'CreationDate': ''},
])
def test_unusable_ancestry_cannot_supply_an_owner(alter):
    child = row(3, 2, 'C:/base/python.exe', 'C:/base/python.exe -m conpact.mcp_server')
    wrapper = row(2, 1, PYTHON, f'{PYTHON} -m conpact.mcp_server')
    wrapper.update(alter)
    assert resolve([child, wrapper]) == 2


def test_changed_parent_edge_refuses():
    assert resolve([row(3, 8, 'python', 'python x'), row(2, 1, PYTHON, PYTHON + ' x')]) == 2


def test_final_owner_must_be_observed_and_predate_child():
    rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{ENTRY}"'),
            row(2, 1, PYTHON, f'"{PYTHON}" "{ENTRY}"'),
            row(1, 9, ENTRY, f'"{ENTRY}"')]
    assert rp.resolve(rows, 3, 2, PYTHON, ENTRY) == 2
    owner = row(9, 0, 'C:/app.exe', 'C:/app.exe')
    owner['CreationDate'] = '2099-01-01'
    assert rp.resolve(rows + [owner], 3, 2, PYTHON, ENTRY) == 2


def test_one_executable_is_the_same_path_or_another_name_for_the_same_file(tmp_path):
    (tmp_path / 'bin').mkdir()
    real = tmp_path / 'python.exe'
    real.write_bytes(b'')
    (tmp_path / 'other.exe').write_bytes(b'')
    assert rp._same('C:\\Venv\\python.exe', 'c:/venv/PYTHON.exe')
    assert rp._same(str(real), str(tmp_path / 'bin' / '..' / 'python.exe'))
    assert rp._same(str(real), str(tmp_path / 'other.exe')) is False
    assert rp._same(str(real), str(tmp_path / 'missing.exe')) is False


@pytest.mark.parametrize('one,other', [(None, None), ('', ''), (None, 'x'), ('x', None), (0, 0), (3, 'x')])
def test_nothing_is_the_same_executable_as_a_missing_path(one, other):
    assert rp._same(one, other) is False


def test_a_launcher_named_through_another_path_to_its_file_is_transparent(tmp_path):
    (tmp_path / 'alias').mkdir()
    image = tmp_path / 'python.exe'
    image.write_bytes(b'')
    named = str(tmp_path / 'alias' / '..' / 'python.exe')
    rows = [row(3, 2, 'C:/base/python.exe', '"C:/base/python.exe" -m conpact.mcp_server'),
            row(2, 1, str(image), f'"{named}" -m conpact.mcp_server'),
            row(1, 0, 'C:/app.exe', 'C:/app.exe')]
    assert rp.resolve(rows, 3, 2, named, ENTRY) == 1
    entry_rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{named}"'),
                  row(2, 1, str(image), f'"{named}"'), rows[2]]
    assert rp.resolve(entry_rows, 3, 2, PYTHON, named) == 1


def chain(parents, unreadable=()):
    """A snapshot over pid -> parent pid, recording what it was asked for."""
    asked = []

    def snapshot(pid):
        asked.append(pid)
        return None if pid in unreadable else dict(ProcessId=pid, ParentProcessId=parents[pid])
    return snapshot, asked


def test_reader_walks_this_process_and_three_ancestors(monkeypatch):
    monkeypatch.setattr(rp.os, 'getpid', lambda: 5)
    snapshot, asked = chain({5: 4, 4: 3, 3: 2, 2: 1, 1: 0})
    assert [r['ProcessId'] for r in rp._read(snapshot)] == [5, 4, 3, 2]
    assert asked == [5, 4, 3, 2]
    monkeypatch.setattr(rp.os, 'getpid', lambda: 2)
    snapshot, asked = chain({2: 1, 1: 0})
    assert [r['ProcessId'] for r in rp._read(snapshot)] == [2, 1] and asked == [2, 1]


@pytest.mark.parametrize('parent', [0, -1, None, '4'])
def test_reader_stops_at_a_parent_that_is_no_process(monkeypatch, parent):
    monkeypatch.setattr(rp.os, 'getpid', lambda: 5)
    snapshot, asked = chain({5: parent})
    assert rp._read(snapshot) == [dict(ProcessId=5, ParentProcessId=parent)]
    assert asked == [5]


def test_reader_stops_at_a_process_it_cannot_read(monkeypatch):
    monkeypatch.setattr(rp.os, 'getpid', lambda: 5)
    snapshot, asked = chain({5: 4, 4: 3}, unreadable={4})
    assert rp._read(snapshot) == [dict(ProcessId=5, ParentProcessId=4)]
    assert asked == [5, 4]
    snapshot, asked = chain({}, unreadable={5})
    assert rp._read(snapshot) == [] and asked == [5]


def test_reader_reads_through_win_process_by_default(monkeypatch):
    monkeypatch.setattr(rp.os, 'getpid', lambda: 5)
    snapshot, asked = chain({5: 0})
    monkeypatch.setattr(rp.win_process, 'snapshot', snapshot)
    assert rp._read() == [dict(ProcessId=5, ParentProcessId=0)] and asked == [5]


def test_owner_unwraps_this_installations_console_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(rp.sys, 'platform', 'win32')
    monkeypatch.setattr(rp.sys, 'prefix', str(tmp_path))
    monkeypatch.setattr(rp.sys, 'base_prefix', str(tmp_path))
    monkeypatch.setattr(rp.os, 'getpid', lambda: 3)
    entry = str(tmp_path / 'Scripts' / 'conpact-mcp.exe')
    rows = [row(3, 2, 'C:/base/python.exe', f'"C:/base/python.exe" "{entry}"'),
            row(2, 1, entry, f'"{entry}"'), row(1, 0, 'C:/app.exe', 'C:/app.exe')]
    assert rp.owner(2, reader=lambda: rows) == 1


def test_base_python_is_not_a_venv_redirector(monkeypatch):
    monkeypatch.setattr(rp.sys, 'platform', 'win32')
    monkeypatch.setattr(rp.sys, 'executable', PYTHON)
    monkeypatch.setattr(rp.sys, 'prefix', rp.sys.base_prefix)
    monkeypatch.setattr(rp.os, 'getpid', lambda: 3)
    rows = [row(3, 2, PYTHON, f'{PYTHON} -m conpact.mcp_server'),
            row(2, 1, PYTHON, f'{PYTHON} -m conpact.mcp_server')]
    assert rp.owner(2, reader=lambda: rows) == 2


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows venv redirector')
def test_real_venv_redirector_resolves_the_process_that_started_it(tmp_path):
    import os
    import subprocess
    import venv
    from pathlib import Path
    folder = tmp_path / 'environment with spaces'
    venv.EnvBuilder(with_pip=False).create(folder)
    env = dict(os.environ, PYTHONPATH=str(Path(rp.__file__).resolve().parents[1]))
    done = subprocess.run([str(folder / 'Scripts' / 'python.exe'), '-c',
                           'import os; from conpact.mcp_tools import Context; '
                           'print(Context.from_runtime().ppid, os.getppid())'],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    owner, redirector = map(int, done.stdout.split())
    assert redirector != os.getpid()
    assert owner == os.getpid()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows venv redirector')
def test_a_venv_started_through_a_junction_resolves_the_process_that_started_it(tmp_path):
    """The OS reports the image by its real path; the venv knows itself by the junction's."""
    import os
    import subprocess
    import venv
    from pathlib import Path
    real, alias = tmp_path / 'real folder', tmp_path / 'alias folder'
    venv.EnvBuilder(with_pip=False).create(real)
    made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(real)], capture_output=True, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    assert made.returncode == 0, made.stdout + made.stderr
    env = dict(os.environ, PYTHONPATH=str(Path(rp.__file__).resolve().parents[1]))
    done = subprocess.run([str(alias / 'Scripts' / 'python.exe'), '-c',
                           'import os, sys; from conpact.mcp_tools import Context; '
                           'print(Context.from_runtime().ppid, os.getppid(), sys.executable)'],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    owner, redirector, executable = done.stdout.split(maxsplit=2)
    assert Path(executable.strip()).parent.parent == alias
    assert int(redirector) != os.getpid()
    assert int(owner) == os.getpid()
