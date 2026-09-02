import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# When frozen by PyInstaller, __file__ points into the one-file extraction
# temp dir, not the exe's location — anchor to the exe instead so talents.json
# and the log file live next to it and stay user-editable. Otherwise anchor to
# the project root (two levels up from this file: holowidget/paths.py).
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent.parent
LOG = ROOT / "start_widget.log"
SETTINGS_PATH = ROOT / "settings.json"
WINDOW_TITLE = "HoloDeskWidget::SingleInstance"
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
_logger = logging.getLogger("holowidget")
_logger.setLevel(logging.ERROR)
_logger.addHandler(_handler)


def log_error(name, error):
    # Used both for per-talent refresh failures and the top-level mainloop
    # fallback, so every entry shares one format and one (append, rotating)
    # write path rather than the two diverging as new call sites are added.
    _logger.error("%s [%s] %s: %s", time.strftime("%Y-%m-%d %H:%M:%S"),
                  name, type(error).__name__, error)
