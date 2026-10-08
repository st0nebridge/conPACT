"""
@module tests.test_codex_sidecar_window
@description The one-click window's logic, with no Tk in it: that it offers
             exactly one action and it is the right one, that clicking it does
             that action and says what happened, and that a refusal or an
             outright failure is a sentence in the window rather than an
             exception out of it.
@input      conpact.codex_sidecar_window.Panel, against a fake installer
@output     assertions on the offered action, the headline, and what a click does
@dependencies conpact.codex_sidecar_window; stdlib: none
"""
import pytest

from conpact import codex_sidecar_window as window


def status(installed=False, running=False, **extra):
    return {"installed": installed, "sidecar_running": running,
            "exe": "/x/codex_sidecar", "env_value": None,
            "store_note": "restart ChatGPT Desktop to apply.", **extra}


class FakeInstaller:
    """What install/uninstall would do, without doing it."""

    def __init__(self, outcome=None, raises=None):
        self.state = status()
        self.outcome = outcome or {"done": True, "detail": None, "message": "installed - ok"}
        self.raises = raises
        self.calls = []

    def read(self):
        return self.state

    def install(self):
        self.calls.append("install")
        if self.raises:
            raise self.raises
        if self.outcome["done"]:
            self.state = status(installed=True)
        return self.outcome

    def uninstall(self):
        self.calls.append("uninstall")
        if self.raises:
            raise self.raises
        if self.outcome["done"]:
            self.state = status(installed=False)
        return self.outcome


def panel(installer):
    return window.Panel(installer.read, installer.install, installer.uninstall)


class TestItOffersExactlyOneAction:
    def test_not_installed_offers_install(self):
        assert panel(FakeInstaller()).action == window.INSTALL

    def test_installed_offers_uninstall(self):
        fake = FakeInstaller()
        fake.state = status(installed=True)
        assert panel(fake).action == window.UNINSTALL

    def test_the_button_says_what_it_will_do(self):
        assert panel(FakeInstaller()).action_text == "Install"
        fake = FakeInstaller()
        fake.state = status(installed=True)
        assert panel(fake).action_text == "Uninstall"

    @pytest.mark.parametrize("installed,running,expected", [
        (False, False, "Not installed."),
        (True, False, "Installed. Restart ChatGPT Desktop to start using it."),
        (True, True, "Installed and ready.")])
    def test_the_headline_says_where_things_stand(self, installed, running, expected):
        fake = FakeInstaller()
        fake.state = status(installed=installed, running=running)
        assert panel(fake).headline == expected


class TestWhatAClickDoes:
    def test_clicking_install_installs_and_then_offers_uninstall(self):
        fake = FakeInstaller()
        p = panel(fake)
        p.click()
        assert fake.calls == ["install"]
        assert p.installed is True
        assert p.action == window.UNINSTALL      # it re-read the world

    def test_clicking_uninstall_uninstalls(self):
        fake = FakeInstaller()
        fake.state = status(installed=True)
        p = panel(fake)
        p.click()
        assert fake.calls == ["uninstall"]
        assert p.installed is False

    def test_it_shows_the_message_the_install_gave_back(self):
        p = panel(FakeInstaller())
        p.click()
        assert p.message == "installed - ok"
        assert p.failed is False

    def test_a_refusal_is_shown_as_a_failure_and_nothing_changes(self):
        fake = FakeInstaller(outcome={"done": False, "detail": None,
                                      "message": "no compiler found"})
        p = panel(fake)
        p.click()
        assert (p.message, p.failed) == ("no compiler found", True)
        assert p.installed is False

    def test_an_installer_that_raises_is_caught_so_the_window_survives(self):
        p = panel(FakeInstaller(raises=OSError("the key is read-only")))
        p.click()
        assert p.failed is True
        assert "OSError" in p.message

    def test_a_second_click_acts_on_what_is_true_now(self):
        """Install then Uninstall, from the one button, with no reopen."""
        fake = FakeInstaller()
        p = panel(fake)
        p.click()
        p.click()
        assert fake.calls == ["install", "uninstall"]


class TestWhatItTellsTheUser:
    def test_it_names_the_shim_so_it_can_be_found(self):
        assert "/x/codex_sidecar" in panel(FakeInstaller()).detail()

    def test_it_repeats_how_the_change_reaches_the_desktop(self):
        assert "restart" in panel(FakeInstaller()).detail().lower()

    def test_it_shows_an_env_value_when_there_is_one(self):
        fake = FakeInstaller()
        fake.state = status(env_value="/x/codex_sidecar")
        assert "CODEX_CLI_PATH" in panel(fake).detail()

    def test_it_says_nothing_about_an_env_value_there_is_not(self):
        assert "CODEX_CLI_PATH" not in panel(FakeInstaller()).detail()


class TestItOpensInItsOwnProcess:
    def test_launch_starts_the_module_detached_with_the_import_root(self):
        seen = {}

        def fake_spawn(argv, env=None):
            seen["argv"], seen["env"] = argv, env
            return 4242

        assert window.launch(spawn=fake_spawn, environ={}) == 4242
        assert seen["argv"][1:] == ["-m", window.MODULE]
        assert seen["env"]["PYTHONPATH"] == window.SRC_ROOT
