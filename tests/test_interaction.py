"""The slider row's shared range/read/write plumbing. Pointer drags, keyboard
Left/Right and the slider drawing in rendering.py all go through these three,
so a mismatch between them is exactly the kind of "the knob says one thing and
the panel does another" bug they exist to prevent."""
import pytest

from deskwidget_core.config import (
    COLUMN_SCALE_MAX,
    COLUMN_SCALE_MIN,
    MIN_BACKGROUND_DARKNESS,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
)
from deskwidget_core.interaction import InteractionMixin

SLIDER_KEYS = ("background", "text", "width")


class FakeWidget(InteractionMixin):
    def __init__(self):
        self.background_alpha = 0.0
        self.text_scale = 1.0
        self.column_scale = 1.0
        self.applied_alpha = None

    def _apply_background_alpha(self):
        # Stands in for the -alpha window attribute, which needs a real Tk
        # window; only that this is called on a background change matters here.
        self.applied_alpha = self.background_alpha


@pytest.mark.parametrize("key", SLIDER_KEYS)
def test_value_starts_inside_its_own_range(key):
    widget = FakeWidget()
    low, high = widget.slider_range(key)

    assert low <= widget.slider_value(key) <= high
    assert 0.0 <= widget.slider_fraction(key) <= 1.0


@pytest.mark.parametrize("key", SLIDER_KEYS)
def test_set_value_round_trips_through_read_back(key):
    widget = FakeWidget()
    low, high = widget.slider_range(key)
    midpoint = low + (high - low) / 2

    widget.set_slider_value(key, midpoint)

    assert widget.slider_value(key) == pytest.approx(midpoint)
    assert widget.slider_fraction(key) == pytest.approx(0.5)


@pytest.mark.parametrize("key", SLIDER_KEYS)
def test_set_value_clamps_to_the_range_at_both_ends(key):
    widget = FakeWidget()
    low, high = widget.slider_range(key)

    widget.set_slider_value(key, high + 10)
    assert widget.slider_value(key) == pytest.approx(high)
    assert widget.slider_fraction(key) == pytest.approx(1.0)

    widget.set_slider_value(key, low - 10)
    assert widget.slider_value(key) == pytest.approx(low)
    assert widget.slider_fraction(key) == pytest.approx(0.0)


def test_background_slider_reads_and_writes_darkness_not_alpha():
    # The value rises to the right like the other two, so it is the inverse of
    # the alpha actually stored/applied.
    widget = FakeWidget()

    widget.set_slider_value("background", 1.0)

    assert widget.background_alpha == pytest.approx(0.0)
    assert widget.applied_alpha == pytest.approx(0.0)

    widget.set_slider_value("background", MIN_BACKGROUND_DARKNESS)

    assert widget.background_alpha == pytest.approx(1.0 - MIN_BACKGROUND_DARKNESS)


def test_each_slider_writes_only_its_own_setting():
    widget = FakeWidget()

    widget.set_slider_value("width", COLUMN_SCALE_MAX)

    assert widget.column_scale == COLUMN_SCALE_MAX
    assert widget.text_scale == 1.0
    assert widget.background_alpha == 0.0


def test_ranges_match_the_configured_bounds():
    widget = FakeWidget()

    assert widget.slider_range("background") == (MIN_BACKGROUND_DARKNESS, 1.0)
    assert widget.slider_range("text") == (TEXT_SCALE_MIN, TEXT_SCALE_MAX)
    assert widget.slider_range("width") == (COLUMN_SCALE_MIN, COLUMN_SCALE_MAX)
