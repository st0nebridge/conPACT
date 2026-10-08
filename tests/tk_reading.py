"""
@module tests.tk_reading
@description Reading a built Tk widget tree back out of Tk, which is how this
             repo verifies a layout (D-20260920-024): what a widget was packed
             with, and the font it was given. Used by both window test modules.
@input      a Tk widget that has been built (it need not be mapped)
@output     plain tuples to compare against
@dependencies stdlib: tkinter (through the widgets passed in)
"""
from __future__ import annotations


def packing(widget):
    """Where the geometry manager was told to put a widget: (side, fill, expand, padx, pady).

    Raises TclError for a widget that was built and then never packed, which is
    exactly the fault worth catching.
    """
    info = widget.pack_info()
    return (info["side"], info["fill"], info["expand"], info["padx"], info["pady"])


def font(widget):
    """The (family, size) a widget was given, back out of Tk's own spelling of it."""
    family, size = str(widget.cget("font")).rsplit(" ", 1)
    return family.strip("{}"), int(size)
