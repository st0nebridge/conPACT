"""The opt-in conPACT launcher and its narrow hooks.json merge."""
import json
import pytest

from conpact import codex_cli, codex_host


def _env(tmp_path):
    home = tmp_path / "codex-home"
    cli = tmp_path / "codex"
    cli.write_text("", encoding="utf-8")
    return {"CODEX_HOME": str(home), "CODEX_CLI_PATH": str(cli), "PATH": ""}


def test_install_preserves_existing_hooks_and_writes_a_backup(tmp_path):
    env = _env(tmp_path)
    path = codex_cli.hooks_path(env)
    path.parent.mkdir(parents=True)
    original = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]}}
    path.write_text(json.dumps(original), encoding="utf-8")
    result = codex_cli.install_hook(env, python="/python")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert result["done"] is True and result["changed"] is True
    assert data["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    assert data["hooks"]["Stop"][1]["hooks"][0]["command"] == \
        codex_cli.hook_command("/python")
    assert json.loads(path.with_name("hooks.json.conpact-backup").read_text()) == original


def test_install_is_idempotent_and_uninstall_removes_only_ours(tmp_path):
    env = _env(tmp_path)
    assert codex_cli.install_hook(env)["changed"] is True
    assert codex_cli.install_hook(env)["changed"] is False
    path = codex_cli.hooks_path(env)
    data = json.loads(path.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "keep-me"}]})
    path.write_text(json.dumps(data))
    assert codex_cli.uninstall_hook(env)["changed"] is True
    kept = json.loads(path.read_text())["hooks"]["Stop"]
    assert kept == [{"hooks": [{"type": "command", "command": "keep-me"}]}]


def test_install_repairs_legacy_hook_without_removing_neighbours(tmp_path):
    env = _env(tmp_path)
    path = codex_cli.hooks_path(env)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': '/python -m conpact.codex_cli_hook'},
        {'type': 'command', 'command': 'keep-me'}]}]}}))
    assert codex_cli.install_hook(env)['changed'] is True
    handlers = json.loads(path.read_text())['hooks']['Stop'][0]['hooks']
    assert handlers[0] == codex_cli.hook_handler()
    assert handlers[1]['command'] == 'keep-me'


def test_launch_keeps_the_token_out_of_argv(tmp_path):
    env = _env(tmp_path)
    codex_cli.install_hook(env)
    seen = {}

    def start(_env):
        codex_host.write_record(61234, 77, "secret-token")
        return {"done": True}

    def execute(program, argv, child_env):
        seen.update(program=program, argv=argv, env=child_env)

    assert codex_cli.launch(["resume", "thread-1"], env, starter=start, execer=execute) == 0
    assert seen["argv"][-2:] == ["resume", "thread-1"]
    assert seen["argv"][1:5] == ["--remote", "ws://127.0.0.1:61234",
                                  "--remote-auth-token-env", codex_cli.AUTH_ENV]
    assert "secret-token" not in " ".join(seen["argv"])
    assert seen["env"][codex_cli.AUTH_ENV] == "secret-token"


def test_launch_refuses_before_starting_when_hook_is_missing(tmp_path):
    env = _env(tmp_path)
    assert codex_cli.launch([], env, starter=lambda _env: (_ for _ in ()).throw(
        AssertionError("must not start")), execer=lambda *_: None) == 1


@pytest.mark.parametrize('body', ['bad-json', '[]', '{"hooks": []}', '{"hooks":{"Stop":{}}}'])
def test_install_refuses_invalid_config_without_overwriting_it(tmp_path, body):
    env = _env(tmp_path)
    path = codex_cli.hooks_path(env)
    path.parent.mkdir(parents=True)
    path.write_text(body)
    assert codex_cli.install_hook(env)['done'] is False
    assert path.read_text() == body


def test_uninstall_preserves_unrecognized_groups_and_handlers(tmp_path):
    env = _env(tmp_path)
    path = codex_cli.hooks_path(env)
    path.parent.mkdir(parents=True)
    groups = [None, {'hooks': 'unknown'}, {'hooks': [None, {'command': 'keep'}]}]
    path.write_text(json.dumps({'hooks': {'Stop': groups}}))
    assert not codex_cli.hook_installed(env)
    assert codex_cli.uninstall_hook(env)['changed'] is False
    assert codex_cli.install_hook(env)['changed'] is True
    assert codex_cli.uninstall_hook(env)['changed'] is True
    assert json.loads(path.read_text())['hooks']['Stop'] == groups


@pytest.mark.parametrize('body', ['bad-json', '{"hooks":{"Stop":{}}}'])
def test_uninstall_refuses_invalid_config_without_overwriting_it(tmp_path, body):
    env = _env(tmp_path)
    path = codex_cli.hooks_path(env)
    path.parent.mkdir(parents=True)
    path.write_text(body)
    assert codex_cli.uninstall_hook(env)['done'] is False
    assert path.read_text() == body


def test_uninstall_without_config_changes_nothing(tmp_path):
    assert codex_cli.uninstall_hook(_env(tmp_path))['changed'] is False


@pytest.mark.parametrize('action', ['install_hook', 'uninstall_hook'])
def test_write_failure_is_reported_without_changing_existing_hooks(tmp_path, monkeypatch, action):
    env = _env(tmp_path)
    codex_cli.install_hook(env)
    path = codex_cli.hooks_path(env)
    original = path.read_bytes()
    def refuse(*args):
        raise OSError('read-only')
    monkeypatch.setattr(codex_cli, '_write_hooks', refuse)
    result = getattr(codex_cli, action)(env, **({'python': 'changed-python'} if action == 'install_hook' else {}))
    assert result['done'] is False and 'read-only' in result['message']
    assert path.read_bytes() == original


@pytest.mark.parametrize('failure', ['cli', 'host', 'record'])
def test_launch_fails_before_exec_when_a_prerequisite_is_missing(tmp_path, monkeypatch, failure):
    env = _env(tmp_path)
    codex_cli.install_hook(env)
    monkeypatch.setattr(codex_cli.codex_appserver, 'codex_cli', lambda env: None if failure == 'cli' else '/codex')
    monkeypatch.setattr(codex_host, 'read_record', lambda: None)
    executed = []
    assert codex_cli.launch([], env, starter=lambda env: {'done': failure != 'host'},
                            execer=lambda *args: executed.append(args)) == 1
    assert executed == []


@pytest.mark.parametrize('verb', ['--install', '--uninstall'])
@pytest.mark.parametrize('done,changed', [(True, True), (True, False), (False, False)])
def test_main_reports_configuration_outcomes(monkeypatch, capsys, verb, done, changed):
    action = 'install_hook' if verb == '--install' else 'uninstall_hook'
    monkeypatch.setattr(codex_cli, action, lambda: {'done': done, 'changed': changed,
                                                  'path': '/hooks.json', 'message': 'refused'})
    assert codex_cli.main([verb]) == (0 if done else 1)
    output = capsys.readouterr()
    assert ('Codex CLI Stop hook' in output.out) if done else ('refused' in output.err)


@pytest.mark.parametrize('installed', [True, False])
def test_main_status_explains_hook_and_server(monkeypatch, capsys, installed):
    monkeypatch.setattr(codex_cli, 'hook_installed', lambda: installed)
    monkeypatch.setattr(codex_host, 'running', lambda: {'ready': installed})
    assert codex_cli.main(['--status']) == (0 if installed else 1)
    assert ('not installed' if not installed else 'hook: installed') in capsys.readouterr().out


def test_main_passes_codex_arguments_unchanged(monkeypatch):
    seen = []
    monkeypatch.setattr(codex_cli, 'launch', lambda args: seen.append(args) or 7)
    assert codex_cli.main(['resume', 'thread-1']) == 7
    assert seen == [['resume', 'thread-1']]


def test_posix_hook_command_quotes_paths_with_spaces():
    import shlex
    assert shlex.split(codex_cli.hook_command('/python with spaces', 'linux')) == [
        '/python with spaces', str(codex_cli.HOOK_ENTRY)]
