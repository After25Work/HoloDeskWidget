"""Shared startup sequence for both variants' start_widget_*.py scripts, so a
future change to it (e.g. a new step, a different exception to catch) only
needs to be made once instead of being kept in sync by hand across variants.
"""
from . import appconfig


def run(profile):
    # configure() must run before any other deskwidget_core module is
    # imported -- paths.py's ROOT/WINDOW_TITLE and theme.py's DEFAULT_ACCENT
    # read the profile at import time (see appconfig.py's own note) -- so the
    # imports below stay inside this function rather than at module scope.
    appconfig.configure(profile)

    from .paths import log_error
    from .single_instance import ensure_single_instance
    from .widget import LayeredWidget

    # Only enforced when run() is actually called (not merely imported), so
    # importing this module for testing/tooling never races a real running
    # instance.
    ensure_single_instance()
    try:
        LayeredWidget().root.mainloop()
    except Exception as error:
        log_error("main", error)
        raise
