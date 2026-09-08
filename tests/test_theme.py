import re

from deskwidget_core import theme


def test_dark_and_light_themes_define_the_same_keys():
    assert set(theme.THEMES["dark"]) == set(theme.THEMES["light"])


def test_production_band_color_alternates_by_position():
    base = (100, 100, 100)

    shaded = theme.production_band_color(base, position=0)
    plain = theme.production_band_color(base, position=1)

    assert shaded == (110, 110, 110)
    assert plain == base


def test_production_band_color_clamps_at_255():
    assert theme.production_band_color((250, 250, 250), position=0, step=10) == (255, 255, 255)


def test_build_theme_palette_has_default_and_monochrome_first():
    palette = theme.build_theme_palette(divisions=23)

    assert palette[0][0] == "Default"
    assert palette[0][1] == theme.DEFAULT_ACCENT
    assert palette[1] == ("Monochrome", theme.MONOCHROME_ACCENT)


def test_build_theme_palette_generates_one_hex_entry_per_division():
    divisions = 5
    palette = theme.build_theme_palette(divisions=divisions)

    assert len(palette) == 2 + divisions
    for label, rgb in palette[2:]:
        assert re.fullmatch(r"#[0-9A-F]{6}", label)
        assert all(0 <= channel <= 255 for channel in rgb)


def test_theme_palette_module_constant_has_25_entries():
    assert len(theme.THEME_PALETTE) == 25
