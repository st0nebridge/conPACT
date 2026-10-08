"""Thin entry point -> conpact.settings_cli: show or change conPACT's settings.

    python tools/settings.py                 open the settings window
    python tools/settings.py show            list every setting
    python tools/settings.py set KEY VALUE   change settings (e.g. set min_context_tokens 150k)
    python tools/settings.py reset [KEY]     back to the defaults
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conpact.settings_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
