import pytest

from deskwidget_core import appconfig


@pytest.fixture(autouse=True)
def restore_profile():
    # appconfig._profile is a process-wide singleton (root conftest.py
    # configures it once for the whole test session, and other already-
    # imported modules like theme.py read it at *their own* import time) --
    # snapshot/restore around each test here so mutating it for one
    # assertion can't leak into unrelated tests run afterward.
    original = dict(appconfig._profile)
    yield
    appconfig._profile.clear()
    appconfig._profile.update(original)


def test_configure_overrides_only_given_keys():
    appconfig.configure({"app_name": "MyWidget"})

    assert appconfig.app_name() == "MyWidget"
    # Untouched keys keep their previous value rather than resetting.
    assert appconfig.version() == appconfig._profile["version"]


def test_title_falls_back_to_japanese_for_unknown_language():
    appconfig.configure({"title": {"ja": "デスク", "en": "Desk"}})

    assert appconfig.title("en") == "Desk"
    assert appconfig.title("fr") == "デスク"


def test_variant_root_and_min_width_reflect_configured_profile():
    appconfig.configure({"variant_root": "/some/path", "min_width": 640})

    assert appconfig.variant_root() == "/some/path"
    assert appconfig.min_width() == 640
