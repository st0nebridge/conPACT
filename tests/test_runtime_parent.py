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


@pytest.mark.parametrize('exe,command', [
    (PYTHON, f'"{PYTHON}" other_script.py'),
    ('C:/foreign/python.exe', '"C:/foreign/python.exe" -m conpact.mcp_server'),
    (ENTRY, f'"{ENTRY}" --different'),
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


@pytest.mark.parametrize('output,expected', [('[]', []), ('{}', []), ('bad', [])])
def test_process_reader_invalid_results_fail_closed(monkeypatch, output, expected):
    from types import SimpleNamespace
    seen = []
    monkeypatch.setattr(rp.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(rp.subprocess, 'run', lambda *a, **k: seen.append((a, k)) or SimpleNamespace(stdout=output))
    assert rp._read() == expected
    assert seen[0][1]['timeout'] == 5
    assert seen[0][1]['creationflags'] == 0x08000000


def test_process_reader_os_failure_fails_closed(monkeypatch):
    def refuse(*a, **k):
        raise OSError('denied')
    monkeypatch.setattr(rp.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    monkeypatch.setattr(rp.subprocess, 'run', refuse)
    assert rp._read() == []


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
                           'from conpact.mcp_tools import Context; print(Context.from_runtime().ppid)'],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert int(done.stdout.strip()) == os.getpid()
