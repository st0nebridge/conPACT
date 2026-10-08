"""Tests for conpact.spin_off: recognising a throwaway worktree checkout."""
import pytest

from conpact import settings, spin_off


@pytest.mark.parametrize("cwd", [
    r"C:\src\conPACT\.claude\worktrees\angry-dirac-98738b",
    "C:/src/conPACT/.claude/worktrees/angry-dirac-98738b",
    r"C:\src\conPACT\.claude\worktrees\angry-dirac-98738b\src\conpact",
    "/home/me/proj/.claude/worktrees/w1",
])
def test_a_checkout_under_claude_worktrees_is_a_spin_off(cwd):
    assert spin_off.is_spin_off(cwd) is True


@pytest.mark.parametrize("cwd", [
    r"C:\src\conPACT",
    r"C:\src\conPACT\.claude",
    # The folder that holds them is not itself a checkout.
    r"C:\src\conPACT\.claude\worktrees",
    # A desktop scratch workspace is a session the user talks in, not one that is
    # merged and archived, so it is deliberately out of scope.
    r"C:\Users\<you>\AppData\Roaming\Claude\scratch-workspaces\f5a74ef6\68ffed3c\scratch-2026-09-19",
    r"C:\Dev\worktrees\mine",          # not under .claude
    r"C:\Dev\.claude\skills\worktrees",  # the two parts are not adjacent
    "",
    None,
    42,
])
def test_everything_else_is_not(cwd):
    assert spin_off.is_spin_off(cwd) is False


def test_the_two_parts_must_be_adjacent_and_in_that_order():
    assert spin_off.is_spin_off("/p/worktrees/.claude/x") is False


def test_the_names_are_matched_whatever_the_case_windows_uses():
    assert spin_off.is_spin_off(r"C:\Dev\P\.Claude\Worktrees\w1") is True


def test_refuses_only_when_the_setting_is_on():
    checkout = r"C:\Dev\P\.claude\worktrees\w1"
    assert spin_off.refuses(checkout, enabled=True) is True
    assert spin_off.refuses(checkout, enabled=False) is False
    assert spin_off.refuses(r"C:\Dev\P", enabled=True) is False


def test_the_setting_is_read_from_the_user_s_settings_by_default():
    checkout = r"C:\Dev\P\.claude\worktrees\w1"
    assert spin_off.refuses(checkout) is True          # the default is on
    settings.save({spin_off.SETTING: False})
    assert spin_off.refuses(checkout) is False
    settings.save({spin_off.SETTING: True})
    assert spin_off.refuses(checkout) is True


def test_the_refusal_says_what_to_do_instead():
    assert ".claude/worktrees" in spin_off.REFUSAL
    assert "Nothing was queued" in spin_off.REFUSAL
    # It must not read as an error to retry around.
    assert "settings" in spin_off.REFUSAL.lower()
