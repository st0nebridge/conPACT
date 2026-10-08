"""
Regression test for CU-20260923-059 (the settings window fits the screen).

The settings window listed every setting in one column and asked for 1,178
pixels of height at 100% scaling: on a 1920x1080 screen, whose work area is
1,032 pixels high, its Save, Defaults and Close buttons were below the bottom
edge, and the window cannot be resized. The settings are now on tabs. The
contract:

  1. Every setting is on exactly one tab, so none can be missing from the
     window, and none shows twice.
  2. The window asks for no more than MAX_HEIGHT pixels at 96 DPI whichever tab
     is showing, and the same height for every tab, so switching never moves
     the buttons. MAX_HEIGHT leaves room for the title bar on the smallest
     common work areas: 1366x768 at 100% (728 high) and 1920x1080 at 150% (672
     at 96 DPI).
  3. Only the chosen tab's page is on screen. A click on a tab shows its page,
     and Ctrl+Tab and Ctrl+Shift+Tab step through them, wrapping round.
  4. The keyboard never types into a page that is not showing: changing tab
     moves the focus to the new page's first box, or to the window itself when
     the page has none, and the window opens with the focus on the first box of
     the first tab.
  5. A value refused on a page that is not showing brings that page forward,
     and its tab is marked in the error colour until the value is accepted.
"""
import pytest

from conpact import settings, settings_window as sw
import window_guard

tk = pytest.importorskip("tkinter")

MAX_HEIGHT = 600


@pytest.fixture
def root():
    # Measured at 96 DPI, whatever this screen is.
    yield from window_guard.root(tk, prepare=lambda window: window.tk.call("tk", "scaling", 96 / 72))


def _view(root):
    view = sw.SettingsView(root, sw.Form(), sw.ui_style.PALETTES["dark"])
    root.update()
    return view


def _names():
    return [name for name, _ in sw.TABS]


def test_every_setting_is_on_exactly_one_tab():
    keys = [key for _, keys in sw.TABS for key in keys]
    assert sorted(keys) == sorted(s.key for s in settings.SETTINGS)
    assert len(keys) == len(set(keys))
    assert all(keys for _, keys in sw.TABS) and len(sw.TABS) > 1


def test_each_setting_is_built_on_the_page_of_its_tab(root):
    view = _view(root)
    for name, keys in sw.TABS:
        for key in keys:
            assert str(view.labels[key]).startswith(str(view.pages[name]) + ".")


def test_the_window_fits_a_small_screen_and_keeps_its_size_across_tabs(root):
    view = _view(root)
    heights = []
    for name in _names():
        view.select(name)
        root.update_idletasks()
        heights.append(root.winfo_reqheight())
    assert max(heights) <= MAX_HEIGHT, heights
    assert len(set(heights)) == 1, heights


def test_only_the_chosen_page_is_on_screen_and_a_click_on_a_tab_changes_it(root):
    view = _view(root)
    first, second, *_ = _names()
    assert view.tab == first
    assert [view.pages[n].winfo_manager() for n in _names()] == ["grid"] + [""] * (len(sw.TABS) - 1)
    view.tabs[second].event_generate("<ButtonRelease-1>")
    assert view.tab == second
    assert [n for n in _names() if view.pages[n].winfo_manager() == "grid"] == [second]


def test_ctrl_tab_steps_through_the_tabs_and_wraps_round(root):
    """The keys are read back from Tk and the steps driven through the events
    they are bound to: a generated key press reaches a window only while it has
    the keyboard, which a test must not take from the user."""
    view = _view(root)
    assert root.event_info(sw.NEXT_TAB) == ("<Control-Key-Tab>",)
    assert "<Control-Shift-Key-Tab>" in root.event_info(sw.PREVIOUS_TAB)
    names = _names()
    seen = []
    for _ in names:
        root.event_generate(sw.NEXT_TAB)
        seen.append(view.tab)
    assert seen == names[1:] + names[:1]
    root.event_generate(sw.PREVIOUS_TAB)
    assert view.tab == names[-1]
    assert view.step(1) == "break"          # or Tk's own Tab binding moves the focus on again


def test_the_focus_follows_the_page_that_is_showing(root, monkeypatch):
    from conpact import desktop
    # show() centres the window in the work area: the real one put this test's
    # window in the middle of the user's screen (CU-20260924-063).
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (-6000, -5000, -3000, -2000))
    view = _view(root)
    for name in ("deiconify", "lift", "focus_force"):   # never take the keyboard from the user
        monkeypatch.setattr(root, name, lambda: None)
    view.show()
    first_box = {name: next((view.entries[k] for k in keys if k in view.entries), None) for name, keys in sw.TABS}
    assert root.focus_lastfor() is first_box[sw.TABS[0][0]]
    for name in _names():
        view.select(name)
        root.update()                         # Tk hands the focus over once the page is mapped
        assert root.focus_lastfor() is (first_box[name] or root), name


def test_a_value_refused_on_a_hidden_page_brings_it_forward_and_marks_its_tab(root):
    view = _view(root)
    key = "closure_min_context_tokens"
    name = next(n for n, keys in sw.TABS if key in keys)
    assert view.tab != name
    view.entries[key].delete(0, "end")
    view.entries[key].insert(0, "lots")
    view.save()
    assert view.tab == name and view.pages[name].winfo_manager() == "grid"
    assert view.tabs[name].cget("fg") == view.p["error"]
    assert all(view.tabs[n].cget("fg") != view.p["error"] for n in _names() if n != name)
    view.entries[key].delete(0, "end")
    view.save()
    assert view.tabs[name].cget("fg") != view.p["error"]
