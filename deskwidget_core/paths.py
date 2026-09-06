import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import appconfig

# When frozen by PyInstaller, __file__ points into the one-file extraction
# temp dir, not the exe's location -- anchor to the exe instead so
# productions/, clock_zones.json, settings.json and the log file live next
# to it and stay user-editable. Otherwise anchor to the current variant's own
# directory (see appconfig.configure(), called by each start_widget_*.py
# before this module is ever imported) so each variant reads/writes its own
# data when run from source instead of sharing one root.
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else appconfig.variant_root()
LOG = ROOT / "start_widget.log"
SETTINGS_PATH = ROOT / "settings.json"
# Derived from the variant's app name (not a bare fixed string) so a sibling
# variant built from this same codebase -- e.g. VTDeskWidget alongside
# HoloDeskWidget -- gets its own window title/single-instance mutex instead
# of colliding with this one.
WINDOW_TITLE = f"{appconfig.app_name()}::SingleInstance"
SW_RESTORE = 9

# Bounds start_widget.log so a long uptime with recurring network errors
# (one check_one() failure per talent per refresh cycle) can't grow it
# without limit; RotatingFileHandler keeps a couple of prior copies around
# for post-mortem context instead of just truncating.
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 2

_handler = RotatingFileHandler(str(LOG), maxBytes=MAX_LOG_BYTES,
                                backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger = logging.getLogger("deskwidget_core")
_logger.setLevel(logging.ERROR)
_logger.addHandler(_handler)


def log_error(name, error):
    # Used both for per-talent refresh failures and the top-level mainloop
    # fallback, so every entry shares one format and one (append, rotating)
    # write path rather than the two diverging as new call sites are added.
    _logger.error("%s [%s] %s: %s", time.strftime("%Y-%m-%d %H:%M:%S"),
                  name, type(error).__name__, error)
