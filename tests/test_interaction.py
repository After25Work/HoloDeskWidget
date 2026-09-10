"""The slider row's shared range/read/write plumbing. Pointer drags, keyboard
Left/Right and the slider drawing in rendering.py all go through these three,
so a mismatch between them is exactly the kind of "the knob says one thing and
the panel does another" bug they exist to prevent."""
import pytest

from deskwidget_core.config import (
    COLUMN_SCALE_MAX,
    COLUMN_SCALE_MIN,
    MIN_BACKGROUND_DARKNESS,
    MIN_HEIGHT,
    MIN_WIDTH,
    NAME_SCALE_MAX,
    NAME_SCALE_MIN,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
)
from deskwidget_core import interaction
from deskwidget_core.interaction import InteractionMixin

SLIDER_KEYS = ("background", "text", "width", "name")


class FakeWidget(InteractionMixin):
    def __init__(self):
        self.background_alpha = 0.0
        self.text_scale = 1.0
        self.column_scale = 1.0
        self.name_scale = 1.0
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
    assert widget.name_scale == 1.0


def test_name_and_width_sliders_are_independent_of_each_other():
    # The title view's name/title split and the plain grid's column pitch
    # used to share one slider, so neither could be set without moving the
    # other; they are two separate controls now.
    widget = FakeWidget()

    widget.set_slider_value("name", NAME_SCALE_MAX)

    assert widget.name_scale == NAME_SCALE_MAX
    assert widget.column_scale == 1.0

    widget.set_slider_value("width", COLUMN_SCALE_MIN)

    assert widget.name_scale == NAME_SCALE_MAX


def test_ranges_match_the_configured_bounds():
    widget = FakeWidget()

    assert widget.slider_range("background") == (MIN_BACKGROUND_DARKNESS, 1.0)
    assert widget.slider_range("text") == (TEXT_SCALE_MIN, TEXT_SCALE_MAX)
    assert widget.slider_range("width") == (COLUMN_SCALE_MIN, COLUMN_SCALE_MAX)
    assert widget.slider_range("name") == (NAME_SCALE_MIN, NAME_SCALE_MAX)


class FakeEvent:
    def __init__(self, x_root, y_root):
        self.x_root, self.y_root = x_root, y_root


class FakeRoot:
    def __init__(self):
        self.geometry_calls = []

    def geometry(self, spec):
        self.geometry_calls.append(spec)


class ResizeFakeWidget(InteractionMixin):
    # Only what drag_move()'s resize branch itself touches -- request_render()
    # is a recording stub rather than the real coalescing one, since that
    # needs a live Tk root's after_idle to fire; this test only cares whether
    # drag_move() hands the window's own geometry to root.geometry()
    # immediately, not what request_render() schedules for the content redraw.
    def __init__(self, edge, origin):
        self.root = FakeRoot()
        self.name_boundary_drag = None
        self.column_boundary_drag = None
        self.resize_drag = True
        self.active_resize_edge = edge
        self.resize_origin = origin
        self.render_requests = 0

    def request_render(self):
        self.render_requests += 1


def test_resize_drag_applies_window_geometry_on_every_pointer_move():
    # A slow content redraw must never gate the window's own box from
    # tracking the pointer: on a large roster, compute_grid() + the full
    # Pillow redraw can take tens to hundreds of milliseconds (see
    # resize_profile.py in the dev scratch used to diagnose this), so
    # queuing the geometry() call behind that same coalesced render -- as
    # opposed to the plain window-drag path below, which already applies
    # its own geometry() synchronously -- is what made a resize drag feel
    # stuttery: the visible window edge only moved once per slow render
    # instead of on every pointer move.
    widget = ResizeFakeWidget("e", origin=(1000, 500, 700, 700, 100, 100))

    widget.drag_move(FakeEvent(x_root=1050, y_root=500))
    widget.drag_move(FakeEvent(x_root=1120, y_root=500))

    assert widget.root.geometry_calls == ["750x700+100+100", "820x700+100+100"]
    # The (still expensive) content redraw stays coalesced -- one request per
    # pointer move, same as before -- this fix only changes when geometry()
    # itself is applied.
    assert widget.render_requests == 2


def test_resize_drag_moves_the_origin_when_dragging_the_near_edge():
    # Dragging the "w"/"n" edges keeps the opposite edge fixed, so the
    # window's origin has to move along with its size -- unlike the "e"/"s"
    # case above, where the origin never changes.
    widget = ResizeFakeWidget("w", origin=(1000, 500, 700, 700, 100, 100))

    widget.drag_move(FakeEvent(x_root=950, y_root=500))

    assert widget.root.geometry_calls == ["750x700+50+100"]


def test_resize_drag_clamps_to_the_configured_min_size():
    widget = ResizeFakeWidget("se", origin=(1000, 500, MIN_WIDTH, MIN_HEIGHT, 100, 100))

    widget.drag_move(FakeEvent(x_root=1000 - MIN_WIDTH, y_root=500 - MIN_HEIGHT))

    assert widget.root.geometry_calls == [f"{MIN_WIDTH}x{MIN_HEIGHT}+100+100"]


class ThrottleFakeRoot:
    # Records how request_render() asked to be called back, without actually
    # running a Tk event loop -- idle_calls/after_calls let a test tell "ran
    # as soon as possible" (after_idle) apart from "deliberately delayed"
    # (after(ms, ...)) without needing a real mainloop.
    def __init__(self):
        self.idle_calls = 0
        self.after_calls = []
        self._pending = None

    def after_idle(self, callback):
        self.idle_calls += 1
        self._pending = callback

    def after(self, delay_ms, callback):
        self.after_calls.append(delay_ms)
        self._pending = callback

    def fire_pending(self):
        callback, self._pending = self._pending, None
        callback()


class ThrottleFakeWidget(InteractionMixin):
    def __init__(self):
        self.root = ThrottleFakeRoot()
        self.render_pending = False
        self._last_render_at = None
        self.render_calls = 0

    def render(self):
        self.render_calls += 1


def test_request_render_runs_immediately_when_nothing_rendered_yet(monkeypatch):
    widget = ThrottleFakeWidget()
    monkeypatch.setattr(interaction.time, "monotonic", lambda: 100.0)

    widget.request_render()

    assert widget.root.idle_calls == 1
    assert widget.root.after_calls == []


def test_request_render_still_coalesces_a_burst_before_the_callback_fires(monkeypatch):
    # Several drag_move() calls between one idle tick and the next must still
    # add up to exactly one scheduled callback, same as before throttling --
    # this is what keeps a burst of pointer moves from queuing a backlog of
    # renders.
    widget = ThrottleFakeWidget()
    monkeypatch.setattr(interaction.time, "monotonic", lambda: 100.0)

    widget.request_render()
    widget.request_render()
    widget.request_render()

    assert widget.root.idle_calls == 1
    assert widget.render_calls == 0


def test_request_render_throttles_a_request_right_after_the_last_render(monkeypatch):
    # render() itself can take tens to hundreds of milliseconds on a large
    # roster (see the resize/render profiling this throttle grew out of);
    # once the event queue is fast enough to drain between renders (a small
    # roster, a fast machine), request_render()'s own coalescing no longer
    # limits the redraw rate on its own -- without this, a burst of pointer
    # moves could trigger far more full redraws than any display refresh
    # could ever show, burning CPU for frames nobody sees.
    widget = ThrottleFakeWidget()
    clock = {"t": 100.0}
    monkeypatch.setattr(interaction.time, "monotonic", lambda: clock["t"])

    widget.request_render()
    widget.root.fire_pending()
    assert widget.render_calls == 1

    widget.request_render()

    assert widget.root.idle_calls == 1  # unchanged -- no second immediate run
    assert widget.root.after_calls == [interaction._RENDER_MIN_INTERVAL_MS]


def test_request_render_stops_throttling_once_the_interval_has_passed(monkeypatch):
    widget = ThrottleFakeWidget()
    clock = {"t": 100.0}
    monkeypatch.setattr(interaction.time, "monotonic", lambda: clock["t"])

    widget.request_render()
    widget.root.fire_pending()
    clock["t"] += interaction._RENDER_MIN_INTERVAL_MS / 1000

    widget.request_render()

    assert widget.root.idle_calls == 2
    assert widget.root.after_calls == []
