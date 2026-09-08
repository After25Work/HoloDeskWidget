"""Root conftest: configures appconfig with a throwaway variant root before
any test module imports anything from deskwidget_core. paths.py (imported by
most of the package) reads appconfig.variant_root() and opens its log file
handler at import time, so this must run at collection time -- not inside a
fixture, which would run too late.
"""
import atexit
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskwidget_core import appconfig

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="deskwidget_test_"))
atexit.register(shutil.rmtree, _TEST_ROOT, True)

appconfig.configure({
    "app_name": "DeskWidgetTest",
    "version": "0.0.0-test",
    "variant_root": _TEST_ROOT,
})
