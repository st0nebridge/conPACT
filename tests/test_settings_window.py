"""Tests for conpact.settings_window: the settings form, its window, and how it is opened."""
import os

import pytest

from conpact import detach, idle_state, settings, settings_window as sw
from tk_reading import font as _font, packing as _packing
import window_guard
import window_process

tk = pytest.importorskip("tkinter")


# --- the form, without Tk ----------------------------------------------------

def test_the_form_starts_from_the_saved_settings():
    settings.save({"min_context_tokens": 150_000, "idle_toast": False})
    form = sw.Form()
    assert form.on == {settings.TOGGLE: False, settings.GUARD_SPIN_OFF: True}
    assert form.text == {"min_context_fill": "50", "min_context_tokens": "150,000",
                         "lead_seconds": "300", "idle_seconds": "",
                         "early_toast_seconds": "120", "mute_seconds": "86,400",
                         "closure_min_context_tokens": "", "result_seconds": "8"}
    assert (form.errors, form.message) == ({}, "")


def test_saving_stores_only_what_changed():
    form = sw.Form()
    settings.save({"lead_seconds": 600})  # changed elsewhere after the form opened
    form.set_text("min_context_tokens", "150k")
    form.set_text("idle_seconds", "60")
    assert form.save() is True
    assert settings.load() == {**settings.defaults(), "min_context_tokens": 150_000, "idle_seconds": 60,
                               "lead_seconds": 600}
    assert form.text["min_context_tokens"] == "150,000" and form.text["lead_seconds"] == "600"
    assert form.message == "Saved. New values apply from the next turn end."


def test_saving_the_toggle():
    form = sw.Form()
    form.toggle(settings.TOGGLE)
    assert form.on[settings.TOGGLE] is False and form.save() is True
    assert idle_state.off_switch_path().exists()
    form.toggle(settings.TOGGLE)
    assert form.save() is True and not idle_state.off_switch_path().exists()


def test_each_on_off_setting_has_its_own_button_and_they_do_not_move_together():
    form = sw.Form()
    form.toggle(settings.GUARD_SPIN_OFF)
    assert form.on == {settings.TOGGLE: True, settings.GUARD_SPIN_OFF: False}
    assert form.save() is True
    # The idle toast stays a file, not a stored value; the other is stored.
    assert settings.load()[settings.GUARD_SPIN_OFF] is False
    assert settings.load()[settings.TOGGLE] is True
    assert not idle_state.off_switch_path().exists()


def test_saving_nothing_changed():
    form = sw.Form()
    form.set_text("min_context_tokens", "100000")
    assert form.save() is True
    assert form.message == "Nothing changed." and not settings.settings_path().exists()


def test_a_refused_value_marks_its_field_and_saves_nothing():
    form = sw.Form()
    form.set_text("min_context_tokens", "150k")
    form.set_text("lead_seconds", "5")
    form.set_text("result_seconds", "")
    assert form.save() is False
    assert form.errors == {"lead_seconds": "Must be from 10 to 86,400 seconds.",
                           "result_seconds": "Needs a value (1 to 600 seconds)."}
    assert form.message == "Not saved: fix the marked values."
    assert not settings.settings_path().exists()
    form.set_text("lead_seconds", "600")
    form.set_text("result_seconds", "8")
    assert form.save() is True and form.errors == {}


def test_a_failed_write_is_reported(monkeypatch):
    form = sw.Form()
    form.set_text("lead_seconds", "600")

    def broken(changes):
        raise OSError("disk full")
    monkeypatch.setattr(settings, "save", broken)
    assert form.save() is False and form.message == "Not saved: disk full"


def test_defaults_fill_the_form_without_saving():
    settings.save({"min_context_tokens": 150_000, "idle_toast": False})
    form = sw.Form()
    form.set_text("lead_seconds", "5")
    form.save()
    form.fill_defaults()
    assert form.on[settings.TOGGLE] is True and form.text["min_context_tokens"] == "100,000" and form.errors == {}
    assert form.message == "Defaults filled in. Save to keep them."
    assert settings.load()["min_context_tokens"] == 150_000
    assert form.save() is True and settings.load() == settings.defaults()


# --- the window ------------------------------------------------------------------

@pytest.fixture
def root():
    yield from window_guard.root(tk)


def _view(root):
    view = sw.SettingsView(root, sw.Form(), sw.ui_style.PALETTES["dark"])
    root.update()  # map the widgets: Tk drops events sent to unmapped ones
    return view


def _type(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def test_the_window_shows_every_setting(root):
    view = _view(root)
    assert root.title() == "conPACT settings"
    for s in settings.SETTINGS:
        assert view.labels[s.key].cget("text") == s.label
    assert set(view.entries) == {s.key for s in settings.SETTINGS if s.unit}
    assert view.entries["min_context_tokens"].get() == "100,000"
    assert view.units["min_context_tokens"].cget("text") == "tokens   default 100,000"
    assert view.units["idle_seconds"].cget("text") == "seconds   default off"
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "On"


def test_save_from_the_window(root):
    view = _view(root)
    _type(view.entries["min_context_tokens"], "150k")
    view.buttons["save"].event_generate("<ButtonRelease-1>")
    assert settings.load()["min_context_tokens"] == 150_000
    assert view.entries["min_context_tokens"].get() == "150,000"
    assert view.status.cget("text") == "Saved. New values apply from the next turn end."


def test_a_refused_value_is_marked_in_the_window(root):
    view = _view(root)
    _type(view.entries["lead_seconds"], "5")
    view.save()
    assert view.error_labels["lead_seconds"].cget("text") == "Must be from 10 to 86,400 seconds."
    assert view.error_labels["min_context_tokens"].cget("text") == ""
    assert view.status.cget("text") == "Not saved: fix the marked values."
    assert view.status.cget("fg") == view.p["error"]
    _type(view.entries["lead_seconds"], "600")
    view.save()
    assert view.error_labels["lead_seconds"].cget("text") == ""


def test_the_toggle_and_defaults_in_the_window(root):
    settings.save({"min_context_tokens": 150_000})
    view = _view(root)
    view.toggle_buttons[settings.TOGGLE].event_generate("<ButtonRelease-1>")
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "Off"
    view.buttons["defaults"].event_generate("<ButtonRelease-1>")
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "On" and view.entries["min_context_tokens"].get() == "100,000"
    assert settings.load()["min_context_tokens"] == 150_000
    view.save()
    assert settings.load() == settings.defaults()


def test_keys_and_close(root):
    view = _view(root)
    assert root.bind("<Return>") and root.bind("<Escape>")
    assert root.protocol("WM_DELETE_WINDOW")
    view.buttons["close"].event_generate("<ButtonRelease-1>")
    assert view.closed and root.state() == "withdrawn"
    view.close()  # a second close does nothing


def test_a_refusal_reads_as_a_sentence():
    assert sw._short("k", ValueError("k must be odd")) == "Must be odd."
    assert sw._short("k", ValueError("k is done.")) == "Is done."


def test_sizes_scale_and_never_reach_zero(root):
    view = sw.SettingsView(root, sw.Form(), sw.ui_style.PALETTES["dark"], scale=1.5)
    assert (view.px(4), view.px(0.1), view.px(0)) == (6, 1, 1)
    # Spelled out rather than as px(sw.WIDTH - 44): computing the expectation from
    # WIDTH would move both sides of the assertion together and prove nothing.
    assert sw.WIDTH == 460
    assert int(str(view.status.cget("wraplength"))) == 624       # (460 - 44) * 1.5


def test_the_window_is_styled_and_laid_out(root):
    view = _view(root)
    p = view.p
    assert root.cget("bg") == p["bg"] and root.resizable() == (False, False)
    texts = [w.cget("text") for w in _labels(root)]
    assert "✳  conPACT" in texts and "Settings" in texts
    for s in settings.SETTINGS:
        assert s.help in texts
        assert view.labels[s.key].winfo_manager() == "pack"
    assert all(entry.winfo_manager() == "pack" for entry in view.entries.values())
    assert all(unit.winfo_manager() == "pack" for unit in view.units.values())
    assert {a: b.cget("text") for a, b in view.buttons.items()} == {"save": "Save", "defaults": "Defaults",
                                                                   "close": "Close"}
    assert view.buttons["close"].pack_info()["side"] == "right"
    assert view.buttons["save"].pack_info()["side"] == "left"


def _labels(widget):
    for child in widget.winfo_children():
        if child.winfo_class() == "Label":
            yield child
        yield from _labels(child)


def test_the_window_is_laid_out_the_way_it_is(root):
    """Every widget the form is built from, where it sits, and the size it was
    given. A mutation run showed none of these values was checked: a padding, a
    font size, the entry's width or the accent stripe could change, or a whole
    `.pack()` call go, and every other test still passed.
    """
    view = _view(root)
    px, p = view.px, view.p

    outer, = root.winfo_children()
    assert _packing(outer) == ("top", "both", 1, 0, 0)
    stripe, content = outer.winfo_children()
    assert _packing(stripe) == ("left", "y", 0, 0, 0)
    assert int(stripe.cget("width")) == px(4)
    assert _packing(content) == ("left", "both", 1, 0, 0)
    assert (int(content.cget("padx")), int(content.cget("pady"))) == (px(20), px(16))

    brand, title, strip, rule, book, status, buttons = content.winfo_children()
    assert brand.cget("text") == "✳  " + sw.toast_text.BRAND
    assert (_font(brand), _packing(brand)) == ((sw.ui_style.FONT_STRONG, 8), ("top", "x", 0, 0, 0))
    assert title.cget("text") == "Settings"
    assert (_font(title), _packing(title)) == ((sw.ui_style.FONT_STRONG, 13), ("top", "x", 0, 0, px(4)))

    assert _packing(strip) == ("top", "x", 0, 0, (px(8), 0))
    cells = strip.winfo_children()
    assert len(cells) == len(sw.TABS)
    for (name, _), cell in zip(sw.TABS, cells):
        assert _packing(cell) == ("left", "none", 0, (0, px(18)), 0)
        tab, mark = cell.winfo_children()
        assert tab is view.tabs[name] and tab.cget("text") == name and mark is view.marks[name]
        assert (_font(tab), _packing(tab)) == ((sw.ui_style.FONT_STRONG, 9), ("top", "x", 0, 0, 0))
        assert (int(tab.cget("padx")), int(tab.cget("pady"))) == (0, px(4))
        assert (tab.cget("cursor"), str(tab.cget("takefocus"))) == ("hand2", "0")   # mouse-only, like a button
        assert (_packing(mark), int(mark.cget("height"))) == (("top", "x", 0, 0, 0), px(2))
    assert (_packing(rule), rule.cget("bg"), int(rule.cget("height"))) == (("top", "x", 0, 0, 0), p["border"], 1)
    assert _packing(book) == ("top", "x", 0, 0, 0)
    assert list(book.winfo_children()) == [view.pages[name] for name, _ in sw.TABS]
    tallest = max(page.winfo_reqheight() for page in view.pages.values())
    assert int(book.grid_rowconfigure(0)["minsize"]) == tallest > 0
    assert int(book.grid_columnconfigure(0)["weight"]) == 1

    wrap = 416                                     # the window's width less the stripe and the padding
    rows = []
    for name, keys in sw.TABS:
        view.select(name, focus=False)
        page = view.pages[name]
        info = page.grid_info()
        assert (int(info["row"]), int(info["column"]), info["sticky"]) == (0, 0, "nesw")
        assert len(page.winfo_children()) == len(keys)
        rows += zip((settings.get(key) for key in keys), page.winfo_children())
    assert len(rows) == len(settings.SETTINGS)
    for setting, frame in rows:
        assert _packing(frame) == ("top", "x", 0, 0, (px(10), 0))
        label, line, help_text, error = frame.winfo_children()
        assert (_font(label), _packing(label)) == ((sw.ui_style.FONT_STRONG, 9), ("top", "x", 0, 0, 0))
        assert _packing(line) == ("top", "x", 0, 0, (px(3), 0))
        assert (_font(help_text), int(help_text.cget("wraplength"))) == ((sw.ui_style.FONT, 8), wrap)
        assert _packing(help_text) == ("top", "x", 0, 0, (px(2), 0))
        assert error is view.error_labels[setting.key]
        assert (_font(error), error.cget("text")) == ((sw.ui_style.FONT, 8), "")
        assert error.winfo_manager() == ""          # packed only while there is something to say
        if setting.unit is None:
            toggle, = line.winfo_children()
            assert toggle is view.toggle_buttons[setting.key] and toggle.cget("text") == "On"
            assert (int(toggle.cget("padx")), int(toggle.cget("pady"))) == (px(16), px(4))
            continue
        entry, unit = line.winfo_children()
        assert _packing(entry)[:2] == ("left", "none") and entry.pack_info()["ipady"] == px(3)
        assert (_font(entry), int(entry.cget("width"))) == ((sw.ui_style.FONT, 10), 12)
        assert int(entry.cget("highlightthickness")) == 1      # the focus ring the accent colour draws
        assert (_font(unit), _packing(unit)) == ((sw.ui_style.FONT, 9), ("left", "none", 0, (px(8), 0), 0))

    assert (_font(status), int(status.cget("wraplength"))) == ((sw.ui_style.FONT, 9), wrap)
    assert (status.cget("text"), _packing(status)) == ("", ("top", "x", 0, 0, (px(12), px(8))))
    assert _packing(buttons) == ("top", "x", 0, 0, 0)
    save, defaults, close = buttons.winfo_children()
    assert [_packing(b)[0] for b in (save, defaults, close)] == ["left", "left", "right"]
    assert all(_packing(b)[3] == (0, px(8)) for b in (save, defaults, close))
    for button in (save, defaults, close):
        assert (int(button.cget("padx")), int(button.cget("pady"))) == (px(12), px(6))
    assert (save.cget("bg"), defaults.cget("bg"), close.cget("bg")) == (p["accent"], p["secondary"], p["bg"])


def test_closing_ends_the_loop_from_inside_it(root, monkeypatch):
    """A quit issued before mainloop() runs is lost, which would leave the window
    on screen with nothing driving it - so it is scheduled, at once, from within."""
    view = _view(root)
    scheduled = []
    monkeypatch.setattr(root, "after", lambda ms, *args: scheduled.append((ms, *args)))
    view.close()
    assert scheduled == [(0, root.quit)]


def test_with_no_work_area_the_window_is_centred_on_the_screen(root, monkeypatch):
    """When Windows will not say where the taskbar is, the whole screen is the
    work area - and the window is centred against all four of its edges, not
    just the far two."""
    from conpact import desktop
    monkeypatch.setattr(desktop, "work_area", lambda fallback: fallback)
    view = _view(root)
    root.update_idletasks()
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    # Gaps that divide by neither 2 nor 3 evenly, so a corner that is one pixel
    # out moves the window instead of rounding back to the same place.
    monkeypatch.setattr(root, "winfo_screenwidth", lambda: width + 101)
    monkeypatch.setattr(root, "winfo_screenheight", lambda: height + 100)
    placed = []
    monkeypatch.setattr(root, "geometry", placed.append)
    for name in ("deiconify", "lift", "focus_force"):
        monkeypatch.setattr(root, name, lambda: None)
    view.show()
    assert placed == [f"+{101 // 2}+{100 // 3}"]


def test_show_raises_the_window_and_puts_the_cursor_in_the_first_field(root, monkeypatch):
    """The window is started from a toast, so it opens behind nothing and the
    user can type straight away. Recorded rather than done: a test that really
    took the keyboard would take it from whatever the user was doing."""
    from conpact import desktop
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (-6000, -5000, -3000, -2000))
    view = _view(root)
    done = []
    monkeypatch.setattr(root, "deiconify", lambda: done.append("deiconify"))
    monkeypatch.setattr(root, "lift", lambda: done.append("lift"))
    monkeypatch.setattr(root, "focus_force", lambda: done.append("focus_force"))
    first = view.entries["lead_seconds"]   # the first box on the first tab, not the toggle above it
    monkeypatch.setattr(first, "focus_set", lambda: done.append("focus_set"))
    view.show()
    assert done == ["deiconify", "lift", "focus_force", "focus_set"]


def test_the_toggle_shows_the_saved_state_and_flips_back(root):
    settings.save({"idle_toast": False})
    view = _view(root)
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "Off"
    view.toggle(settings.TOGGLE)
    view.toggle(settings.TOGGLE)
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "Off"
    view.toggle(settings.TOGGLE)
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "On"


def test_one_toggle_button_per_on_off_setting_and_a_click_moves_only_its_own(root):
    view = _view(root)
    assert set(view.toggle_buttons) == {s.key for s in settings.SETTINGS if s.unit is None}
    view.select("Agent")
    root.update()  # Tk drops a click on a page that is not showing
    view.toggle_buttons[settings.GUARD_SPIN_OFF].event_generate("<ButtonRelease-1>")
    assert view.toggle_buttons[settings.GUARD_SPIN_OFF].cget("text") == "Off"
    assert view.toggle_buttons[settings.TOGGLE].cget("text") == "On"


def test_an_error_line_shows_only_while_there_is_an_error(root):
    view = _view(root)
    assert view.error_labels["lead_seconds"].winfo_manager() == ""
    _type(view.entries["lead_seconds"], "5")
    view.save()
    assert view.error_labels["lead_seconds"].winfo_manager() == "pack"
    _type(view.entries["lead_seconds"], "600")
    view.save()
    assert view.error_labels["lead_seconds"].winfo_manager() == ""


def test_the_tabs_are_the_ones_the_settings_page_names():
    """Spelled out rather than read from TABS: docs/settings.md tells the reader
    which tab each setting is on, so a renamed or moved one is a change to both."""
    assert sw.TABS == (
        ("Idle toast", ("idle_toast", "lead_seconds", "mute_seconds", "result_seconds")),
        ("Session size", ("min_context_fill", "min_context_tokens")),
        ("Early toast", ("idle_seconds", "early_toast_seconds")),
        ("Agent", ("closure_min_context_tokens", "guard_spin_off_sessions")),
    )


def test_the_chosen_tab_is_drawn_in_the_text_colour_and_underlined(root):
    view = _view(root)
    p = view.p
    for chosen, _ in sw.TABS:
        view.select(chosen, focus=False)
        for name, _ in sw.TABS:
            assert view.tabs[name].cget("fg") == (p["text"] if name == chosen else p["muted"])
            assert view.marks[name].cget("bg") == (p["accent"] if name == chosen else p["bg"])


def test_a_tab_lights_up_under_the_mouse_and_goes_back_after(root):
    view = _view(root)
    tab = view.tabs["Agent"]
    tab.event_generate("<Enter>")
    assert tab.cget("fg") == view.p["text"]
    tab.event_generate("<Leave>")
    assert tab.cget("fg") == view.p["muted"] and view.tab != "Agent"


def test_a_click_on_a_tab_is_ignored_once_the_window_is_closed(root):
    view = _view(root)
    view.close()
    view.click(sw.TAB_ACTION + "Agent")
    assert view.tab == sw.TABS[0][0]


def test_a_refusal_on_the_page_showing_keeps_it_there(root):
    view = _view(root)
    view.select("Agent", focus=False)
    _type(view.entries["lead_seconds"], "5")          # on the first tab
    _type(view.entries["closure_min_context_tokens"], "lots")
    view.save()
    assert view.tab == "Agent"                         # it has a refusal of its own to show
    assert view.tabs["Idle toast"].cget("fg") == view.tabs["Agent"].cget("fg") == view.p["error"]


def test_the_window_closes_through_the_title_bar_and_ends_its_loop(root):
    view = _view(root)
    root.tk.call(root.protocol("WM_DELETE_WINDOW"))
    assert view.closed
    timed_out = []
    root.after(3000, lambda: timed_out.append(True) or root.quit())
    root.mainloop()
    assert timed_out == []
    view.click("save")  # ignored once closed
    assert view.status.cget("text") == ""


def _hidden_view(root, monkeypatch):
    """The window as run() builds it, withdrawn before it is ever mapped, with
    what show() asks of the window manager recorded instead of done.

    Where a shown window lands is not this code's to decide: on the machine
    these tests were written on, PowerToys FancyZones moves every window a
    process shows onto the monitor under the cursor, from its own process, a
    moment later. A test that mapped the window and read back where it landed
    raced it, and lost now and then under load (CU-20260924-062). It also put
    the window on the user's screen and took their keyboard. So the position is
    read from Tk's own record of what it was asked for, which is what Tk hands
    to Windows, and nothing is ever shown.

    Withdrawn first, as run() does it: building the view lets Tk map a root
    that is not withdrawn (its update_idletasks), which showed the window for
    a moment and, in a fresh process, took the keyboard (CU-20260924-063)."""
    root.withdraw()
    view = sw.SettingsView(root, sw.Form(), sw.ui_style.PALETTES["dark"])
    asked = []
    geometry = root.wm_geometry
    monkeypatch.setattr(root, "geometry", lambda spec: asked.append(("geometry", spec)) or geometry(spec))
    for name in ("deiconify", "lift", "focus_force"):
        monkeypatch.setattr(root, name, lambda name=name: asked.append(name))
    return view, asked


def _placed(root):
    """The window's position as Tk holds it: `wm geometry` reads back WxH+x+y."""
    x, y = root.wm_geometry().split("+")[1:]
    return int(x), int(y)


def test_show_centres_the_window_in_the_work_area(root, monkeypatch):
    from conpact import desktop
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (-6000, -5000, -3000, -2000))
    view, asked = _hidden_view(root, monkeypatch)
    view.show()
    root.update_idletasks()   # the size it has when laid out, whether or not show() waited for that
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    x, y = -6000 + (3000 - width) // 2, -5000 + (3000 - height) // 3
    # Placed before it is shown, so it never appears where it was before.
    assert asked == [("geometry", f"+{x}+{y}"), "deiconify", "lift", "focus_force"]
    assert _placed(root) == (x, y)
    assert not root.winfo_ismapped()


def test_show_keeps_a_window_larger_than_the_work_area_at_its_corner(root, monkeypatch):
    from conpact import desktop
    monkeypatch.setattr(desktop, "work_area", lambda fallback: (-6000, -5000, -5990, -4990))
    view, asked = _hidden_view(root, monkeypatch)
    view.show()
    assert asked == [("geometry", "+-6000+-5000"), "deiconify", "lift", "focus_force"]
    assert _placed(root) == (-6000, -5000)
    assert not root.winfo_ismapped()


# --- opening it ------------------------------------------------------------------

def test_the_path_handed_to_the_child_is_the_root_the_package_imports_from():
    """Asserted against the directory itself, not against sw.SRC_ROOT: comparing it
    to the constant it comes from lets the constant point anywhere and still pass.
    Point it one level out and the child cannot import conpact at all."""
    import pathlib
    root = pathlib.Path(sw.SRC_ROOT)
    assert root.name == "src"
    assert (root / "conpact" / "settings_window.py").is_file()


def test_launch_starts_the_window_as_its_own_process():
    calls = []
    pid = sw.launch(spawn=lambda argv, env: calls.append((argv, env)) or 4321, environ={"X": "1"})
    assert pid == 4321
    assert calls == [([detach.windowless_python(), "-m", "conpact.settings_window"],
                      {"X": "1", "PYTHONPATH": sw.SRC_ROOT})]


def test_main_runs_the_window(monkeypatch):
    opened = []
    monkeypatch.setattr(sw, "run", lambda: opened.append(True))
    assert sw.main() == 0 and opened == [True]


@pytest.mark.real_settings_run
def test_run_opens_a_hidden_window_dressed_by_the_desktop_and_destroys_it_after(monkeypatch):
    """run() is the whole window in one call, and it was proved only by the
    on-screen test below - which runs in a subprocess, where no coverage is
    collected, so every mutant on these lines went unexamined. Here show() is
    stubbed to end the loop at once: nothing is mapped, and nothing takes the
    keyboard from whatever the user is doing.
    """
    from conpact import desktop
    asked, loops, shown, built = [], [], [], {}
    monkeypatch.setattr(desktop, "dpi_aware", lambda: asked.append("dpi"))
    monkeypatch.setattr(desktop, "theme", lambda: "light")
    monkeypatch.setattr(sw.SettingsView, "show",
                        lambda self: shown.append(True) or self.root.after(0, self.root.quit))
    mainloop = tk.Tk.mainloop
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self, n=0: loops.append(True) or mainloop(self, n))
    real = sw.SettingsView

    def spy(window, form, palette, scale):
        built.update(root=window, form=form, palette=palette, scale=scale,
                     dpi=window.winfo_fpixels("1i"), state_when_built=window.state())
        # Five seconds, then give up. Only show() is scheduled to end the loop, so
        # dropping the call to it leaves run() in a mainloop with nothing to quit it:
        # without this the test hangs instead of failing, and a hang is how a real
        # survivor passed for a timeout twice over (D-20260920-025).
        window.after(5000, window.quit)
        return real(window, form, palette, scale)

    monkeypatch.setattr(sw, "SettingsView", spy)
    assert sw.run() is None
    assert asked == ["dpi"] and loops == [True] and shown == [True]
    assert isinstance(built["form"], sw.Form)
    assert built["palette"] is sw.ui_style.PALETTES["light"]
    # The screen's own dpi against the 96 Windows calls 100%: every size in the
    # form is multiplied by this, so a window built at the wrong scale is unusable.
    assert built["scale"] == pytest.approx(built["dpi"] / 96)
    assert built["state_when_built"] == "withdrawn"   # nothing on screen until show() has placed it
    with pytest.raises(tk.TclError):
        built["root"].winfo_exists()                  # and the window is gone on the way out


@pytest.mark.real_settings_run
def test_the_module_run_as_a_command_is_what_opens_the_window(monkeypatch):
    """`launch()` spawns `python -m conpact.settings_window`, so the guard at
    the bottom of the module is the whole of what that command does, and nothing
    else runs it. Break it and the toast's Settings link starts a process that
    shows nothing and exits 0.

    runpy gives the module a fresh namespace, so patching the imported one does
    not reach it: the window is kept off the screen by a Tk that declines to map
    itself or take the keyboard, which the fresh namespace picks up from tkinter.
    """
    import runpy
    import warnings
    from conpact import desktop
    monkeypatch.setattr(desktop, "dpi_aware", lambda: None)

    class Unmapped(tk.Tk):
        def __init__(self):
            super().__init__()
            self.geometry("+-4000+-4000")
            self.after(0, self.quit)         # end the loop the moment it starts

        def deiconify(self):
            pass                             # never mapped ...

        def lift(self, aboveThis=None):
            pass

        def focus_force(self):
            pass                             # ... and never takes the user's keyboard

    monkeypatch.setattr(tk, "Tk", Unmapped)
    with warnings.catch_warnings(), pytest.raises(SystemExit) as stopped:
        # Running an already-imported module warns; running it again is the point.
        warnings.filterwarnings("ignore", "'conpact.settings_window' found in sys.modules",
                                RuntimeWarning)
        runpy.run_module("conpact.settings_window", run_name="__main__")
    assert stopped.value.code == 0


def test_tests_cannot_open_the_real_window(_isolate_user_state):
    with pytest.raises(AssertionError, match="settings window"):
        sw.run()
    assert _isolate_user_state == ["open the settings window"]
    _isolate_user_state.clear()  # this breach was the point of the test


# The window takes the keyboard when it is shown - the user opened it to type,
# and on Windows Tk's deiconify alone takes it. On the user's own desktop that
# handed this test whatever they typed or clicked in the second it was up: one
# digit typed into the first field made a value the save refused, and Escape
# closed the window before the save ran. Either left the default ("saved
# 100000"), now and then in a full run and never alone. Windows sends input only
# to the desktop the user is on, so the script first gives itself a desktop of
# its own: the window is still created, mapped, focused and driven for real, and
# nobody can reach it or lose their keyboard to it.
OWN_DESKTOP = """
import ctypes
import os
if os.name == "nt":
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateDesktopW.restype = user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.LPVOID)
    user32.SetThreadDesktop.argtypes = (wintypes.HANDLE,)
    user32.GetThreadDesktop.argtypes = (wintypes.DWORD,)
    user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                                 wintypes.LPDWORD)
    GENERIC_ALL, UOI_NAME = 0x10000000, 2
    desktop = user32.CreateDesktopW(f"conpact-test-{os.getpid()}", None, None, 0, GENERIC_ALL, None)
    if not desktop or not user32.SetThreadDesktop(desktop):
        raise SystemExit(f"no desktop of its own: Windows error {ctypes.get_last_error()}")
    name = ctypes.create_unicode_buffer(64)
    user32.GetUserObjectInformationW(user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId()),
                                     UOI_NAME, name, ctypes.sizeof(name), None)
    print("desktop", name.value)
"""

WINDOW_ON_SCREEN = """
from conpact import settings, settings_window as sw
shown = sw.SettingsView.show
def show(self):
    shown(self)
    self.root.update()
    focus = next((key for key, entry in self.entries.items() if entry is self.root.focus_get()), None)
    print("mapped", self.root.winfo_ismapped(), "focus", focus)
    self.entries["min_context_tokens"].delete(0, "end")
    self.entries["min_context_tokens"].insert(0, "150k")
    self.root.after(100, self.save)
    self.root.after(300, self.close)
sw.SettingsView.show = show
sw.run()
print("saved", settings.load()["min_context_tokens"])
"""


@pytest.mark.real_ui
def test_the_real_window_shows_saves_and_closes(tmp_path):
    proc = window_process.run(tmp_path, WINDOW_ON_SCREEN,
                              start=OWN_DESKTOP + "from conpact import settings, settings_window")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    if os.name == "nt":
        assert lines[0].startswith("desktop conpact-test-"), proc.stdout
    assert "mapped 1 focus lead_seconds" in lines, proc.stdout   # the cursor in the first tab's first field
    assert lines[-1] == "saved 150000", proc.stdout
    assert (tmp_path / ".conpact" / "settings.json").exists()
