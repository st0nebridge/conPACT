"""Release installation must work outside the checkout and reject bad greetings."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conpact import codex_cli, codex_sidecar, codex_sidecar_install as si, home


@pytest.mark.parametrize('opening', [b'\xff\n', 'wrong-\u00e9\n'.encode(), b'\x00\n'])
def test_untrusted_token_bytes_are_refused(opening):
    assert codex_sidecar.greet('secret', opening) is None


def test_installed_sidecar_uses_writable_state_and_shipped_sources(tmp_path, monkeypatch):
    package = tmp_path / 'read-only-site' / 'conpact'
    sources = package / 'sidecar_resources'
    sources.mkdir(parents=True)
    for name in ('build.cmd', 'codex_launcher.c'):
        (sources / name).write_text(name)
    monkeypatch.setattr(si, '__file__', str(package / 'codex_sidecar_install.py'))
    monkeypatch.setattr(home, 'HOME', tmp_path / 'state')
    called = []

    def compiler(argv, cwd):
        folder = Path(cwd)
        called.append((argv, (folder / 'codex_launcher.c').read_text()))
        (folder / 'codex_sidecar.exe').write_bytes(b'compiled')

    result = si.build('win32', runner=compiler)
    assert result['done'], result
    assert called
    assert called[0][1] == 'codex_launcher.c'
    assert si.sidecar_dir().is_relative_to(home.HOME)
    assert si.launcher_config().read_text().splitlines()[1] == str(package.parent)
    assert sorted(p.name for p in sources.iterdir()) == ['build.cmd', 'codex_launcher.c']


def test_checkout_hook_runs_without_package_on_child_path(tmp_path):
    # -S removes installed site packages; cwd and PYTHONPATH provide no checkout.
    command = codex_cli.hook_command(sys.executable)
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    env['PYTHONNOUSERSITE'] = '1'
    command = command.replace(sys.executable, sys.executable + ' -S', 1)
    result = subprocess.run(command if sys.platform == 'win32' else __import__('shlex').split(command),
                            input='{}', text=True, capture_output=True,
                            cwd=tmp_path, env=env, timeout=20)
    assert result.returncode == 0, result.stderr
