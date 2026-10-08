"""Tests for conpact.settings: the user's settings, their defaults, ranges and storage."""
import json

import pytest

from conpact import compaction, idle_state, settings as st

DEFAULTS = {"idle_toast": True, "min_context_fill": 50, "min_context_tokens": 100_000, "lead_seconds": 300, "idle_seconds": None,
            "early_toast_seconds": 120, "mute_seconds": 86_400, "closure_min_context_tokens": None,
            "guard_spin_off_sessions": True, "result_seconds": 8}


def _file(data):
    st.settings_path().parent.mkdir(parents=True, exist_ok=True)
    st.settings_path().write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _stored():
    return json.loads(st.settings_path().read_text(encoding="utf-8"))


def test_the_settings_and_their_defaults():
    assert [s.key for s in st.SETTINGS] == list(DEFAULTS)
    assert st.defaults() == DEFAULTS
    assert st.load() == DEFAULTS
    assert st.settings_path() == compaction.STATE_DIR / "settings.json"
    for setting in st.SETTINGS:
        assert setting.label and setting.help and setting.help.endswith(".")


@pytest.mark.parametrize("key, low, high", [
    ("min_context_fill", 1, 100),
    ("min_context_tokens", 1, compaction.MAX_CONTEXT_TOKENS),
    ("lead_seconds", 10, 86_400),
    ("idle_seconds", 10, 86_400),
    ("early_toast_seconds", 10, 86_400),
    ("mute_seconds", 60, 604_800),
    ("closure_min_context_tokens", 1, compaction.MAX_CONTEXT_TOKENS),
    ("result_seconds", 1, 600),
])
def test_ranges(key, low, high):
    setting = st.get(key)
    assert (setting.low, setting.high) == (low, high)
    assert st.check(key, low) == low and st.check(key, high) == high
    for bad in (low - 1, high + 1):
        with pytest.raises(ValueError, match=f"{key} must be"):
            st.check(key, bad)


@pytest.mark.parametrize("key, value", [
    ("min_context_tokens", None), ("min_context_tokens", True), ("min_context_tokens", 1.5),
    ("min_context_tokens", "100000"), ("lead_seconds", None), ("result_seconds", None),
    ("idle_toast", None), ("idle_toast", 1), ("idle_toast", "on"),
    ("min_context_fill", None), ("min_context_fill", True), ("min_context_fill", 50.0),
    ("min_context_fill", "50"),
])
def test_check_refuses_the_wrong_kind(key, value):
    with pytest.raises(ValueError, match=key):
        st.check(key, value)


def test_optional_settings_accept_none_and_the_toggle_takes_booleans():
    assert st.check("idle_seconds", None) is None
    assert st.check("closure_min_context_tokens", None) is None
    assert st.check("idle_toast", False) is False


def test_an_unknown_key_names_the_known_ones():
    with pytest.raises(ValueError, match="unknown setting 'lead'.*lead_seconds"):
        st.get("lead")


@pytest.mark.parametrize("key, text, value", [
    ("min_context_fill", "50", 50),
    ("min_context_fill", "50%", 50),          # what `describe` prints, typed back
    ("min_context_fill", " 75 ", 75),
    ("min_context_fill", "1", 1),
    ("min_context_fill", "100", 100),
    ("min_context_tokens", "150000", 150_000),
    ("min_context_tokens", " 150,000 ", 150_000),
    ("min_context_tokens", "150_000", 150_000),
    ("min_context_tokens", "150k", 150_000),
    ("min_context_tokens", "150K", 150_000),
    ("lead_seconds", "600", 600),
    ("idle_seconds", "", None),
    ("idle_seconds", "off", None),
    ("idle_seconds", "None", None),
    ("idle_seconds", "60", 60),
    ("closure_min_context_tokens", "200k", 200_000),
    ("idle_toast", "on", True), ("idle_toast", "Yes", True), ("idle_toast", "true", True), ("idle_toast", "1", True),
    ("idle_toast", "off", False), ("idle_toast", "no", False), ("idle_toast", "FALSE", False),
    ("idle_toast", "0", False),
])
def test_parse(key, text, value):
    assert st.parse(key, text) == value


@pytest.mark.parametrize("key, text, message", [
    ("min_context_tokens", "", "min_context_tokens needs a value"),
    ("min_context_tokens", "off", "min_context_tokens needs a value"),
    ("min_context_tokens", "lots", "min_context_tokens must be a whole number"),
    ("min_context_tokens", "1.5k", "min_context_tokens must be a whole number"),
    ("min_context_tokens", "-5", "min_context_tokens must be a whole number"),
    ("lead_seconds", "5", "lead_seconds must be from 10 to 86,400 seconds"),
    ("min_context_fill", "0", "min_context_fill must be from 1 to 100 percent"),
    ("min_context_fill", "101", "min_context_fill must be from 1 to 100 percent"),
    ("min_context_fill", "", "min_context_fill needs a value"),
    ("min_context_fill", "half", "min_context_fill must be a whole number"),
    ("idle_toast", "maybe", "idle_toast must be on or off"),
])
def test_parse_says_what_is_wrong(key, text, message):
    with pytest.raises(ValueError, match=message):
        st.parse(key, text)


def test_valid_values_in_the_file_override_the_defaults():
    _file({"min_context_tokens": 5000, "lead_seconds": 600, "idle_seconds": 180,
           "closure_min_context_tokens": 150_000, "result_seconds": 20, "other": 1})
    assert st.load() == {**DEFAULTS, "min_context_tokens": 5000, "lead_seconds": 600, "idle_seconds": 180,
                         "closure_min_context_tokens": 150_000, "result_seconds": 20}


def test_an_unusable_value_falls_back_to_its_default_alone():
    _file({"min_context_tokens": "big", "lead_seconds": 5, "idle_seconds": 60, "result_seconds": True})
    assert st.load() == {**DEFAULTS, "idle_seconds": 60}


@pytest.mark.parametrize("bounds", [
    {"min_context_fill": 1, "min_context_tokens": 1, "lead_seconds": 10, "idle_seconds": 10,
     "closure_min_context_tokens": 1, "result_seconds": 1},
    {"min_context_fill": 100, "min_context_tokens": 10_000_000, "lead_seconds": 86_400,
     "idle_seconds": 86_400, "closure_min_context_tokens": 10_000_000, "result_seconds": 600},
])
def test_the_file_may_hold_the_bounds(bounds):
    _file(bounds)
    assert st.load() == {**DEFAULTS, **bounds}


@pytest.mark.parametrize("key, value", [
    ("min_context_tokens", 0), ("min_context_tokens", 10_000_001), ("min_context_tokens", "5000"),
    ("min_context_tokens", True), ("min_context_tokens", 5000.0),
    ("lead_seconds", 9), ("lead_seconds", 86_401), ("lead_seconds", None),
    ("idle_seconds", 9), ("idle_seconds", 86_401), ("idle_seconds", "180"), ("idle_seconds", False),
    ("closure_min_context_tokens", 0), ("closure_min_context_tokens", "150k"),
    ("result_seconds", 0), ("result_seconds", 601), ("result_seconds", None),
    ("min_context_fill", 0), ("min_context_fill", 101), ("min_context_fill", "50"),
    ("min_context_fill", True), ("min_context_fill", None),
])
def test_an_invalid_value_in_the_file_falls_back_to_its_default_alone(key, value):
    good = {"min_context_tokens": 5000, "lead_seconds": 600, "idle_seconds": 180,
            "closure_min_context_tokens": 150_000, "result_seconds": 20}
    _file({**good, key: value})
    assert st.load() == {**DEFAULTS, **good, key: DEFAULTS[key]}


def test_a_key_that_is_not_a_setting_is_ignored_not_checked():
    _file({"colour": "red", "lead_seconds": 600})
    assert st.load() == {**DEFAULTS, "lead_seconds": 600}


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null", "7"])
def test_an_unusable_file_gives_the_defaults(raw):
    _file(raw)
    assert st.load() == DEFAULTS


def test_the_toast_switch_is_the_off_switch_file_not_the_json():
    _file({"idle_toast": False})
    assert st.load()["idle_toast"] is True
    idle_state.off_switch_path().write_text("", encoding="utf-8")
    assert st.load()["idle_toast"] is False


def test_save_stores_only_what_differs_from_the_default():
    assert st.save({"min_context_tokens": 150_000, "lead_seconds": 300}) == {**DEFAULTS, "min_context_tokens": 150_000}
    assert _stored() == {"min_context_tokens": 150_000}
    st.save({"idle_seconds": 60})
    assert _stored() == {"min_context_tokens": 150_000, "idle_seconds": 60}
    st.save({"idle_seconds": None, "min_context_tokens": 100_000})
    assert not st.settings_path().exists()


def test_save_keeps_unrelated_keys_in_the_file():
    _file({"note": "mine", "lead_seconds": 600})
    st.save({"result_seconds": 12})
    assert _stored() == {"note": "mine", "lead_seconds": 600, "result_seconds": 12}


def test_save_switches_the_toast_with_the_off_switch():
    st.save({"idle_toast": False})
    assert idle_state.off_switch_path().exists() and not st.settings_path().exists()
    assert st.load()["idle_toast"] is False
    st.save({"idle_toast": True})
    assert not idle_state.off_switch_path().exists()
    st.save({"idle_toast": True})  # already on: nothing to remove
    assert st.load()["idle_toast"] is True


def test_save_writes_nothing_if_any_value_is_refused():
    with pytest.raises(ValueError, match="lead_seconds"):
        st.save({"min_context_tokens": 150_000, "lead_seconds": 1, "idle_toast": False})
    assert not st.settings_path().exists() and not idle_state.off_switch_path().exists()
    with pytest.raises(ValueError, match="unknown setting"):
        st.save({"min_context_tokens": 150_000, "colour": "red"})
    assert not st.settings_path().exists()


def test_save_over_an_unusable_file_replaces_it():
    _file("not json")
    st.save({"lead_seconds": 600})
    assert _stored() == {"lead_seconds": 600}


def test_save_leaves_no_temporary_file():
    st.save({"lead_seconds": 600})
    assert [p.name for p in st.settings_path().parent.iterdir()] == ["settings.json"]


def test_reset():
    st.save({"min_context_tokens": 150_000, "lead_seconds": 600, "idle_toast": False})
    assert st.reset(["lead_seconds"]) == {**DEFAULTS, "min_context_tokens": 150_000, "idle_toast": False}
    assert st.reset() == DEFAULTS
    assert not st.settings_path().exists() and not idle_state.off_switch_path().exists()
    with pytest.raises(ValueError, match="unknown setting"):
        st.reset(["colour"])


@pytest.mark.parametrize("key, value, text", [
    ("idle_toast", True, "on"), ("idle_toast", False, "off"),
    ("min_context_tokens", 100_000, "100,000 tokens"),
    ("closure_min_context_tokens", None, "off"),
    ("lead_seconds", 300, "300 s"), ("lead_seconds", 90, "90 s"), ("idle_seconds", None, "off"),
    ("result_seconds", 8, "8 s"),
])
def test_describe(key, value, text):
    assert st.describe(key, value) == text


@pytest.mark.parametrize("key, text", [
    ("idle_toast", "on or off"),
    ("min_context_tokens", "1 to 10,000,000 tokens"),
    ("idle_seconds", "10 to 86,400 seconds, or off"),
    ("closure_min_context_tokens", "1 to 10,000,000 tokens, or off"),
])
def test_allowed(key, text):
    assert st.allowed(key) == text


def test_settings_are_read_only_and_their_labels_are_fixed():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.SETTINGS[0].default = False
    assert [s.label for s in st.SETTINGS] == [
        "Idle toast", "Toast only for sessions at least this full",
        "Toast only for sessions of at least", "Show the toast this long before the cache expires",
        "Also show an early toast after an idle time of", "The early toast waits for an answer for",
        "\"Silence this session\" silences it for",
        "Compaction an agent queues: only if the context is at least",
        "Refuse a compaction queued in a worktree session", "Keep the result on screen for"]


def test_the_unknown_key_message_lists_every_key():
    with pytest.raises(ValueError) as exc:
        st.get("lead")
    assert str(exc.value) == ("unknown setting 'lead' (known: idle_toast, min_context_fill, "
                              "min_context_tokens, lead_seconds, "
                              "idle_seconds, early_toast_seconds, mute_seconds, closure_min_context_tokens, "
                              "guard_spin_off_sessions, result_seconds)")


def test_parse_ignores_spaces_inside_a_number():
    assert st.parse("min_context_tokens", "150 000") == 150_000


def test_the_file_is_indented_json_with_a_final_newline():
    st.save({"lead_seconds": 600, "idle_seconds": 60})
    assert st.settings_path().read_text(encoding="utf-8") == '{\n  "lead_seconds": 600,\n  "idle_seconds": 60\n}\n'
