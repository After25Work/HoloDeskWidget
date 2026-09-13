# Multi-select Production Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the top production-tab strip (VT variant, multi-production only) from single-select (one production, or the pseudo "All" tab) into multi-select, where any combination of visible productions can be toggled on/off and the view merges exactly that combination.

**Architecture:** Replace `LayeredWidget.active_production` (a single id) with `LayeredWidget.selected_productions` (a `set` of real production ids). The merge logic the "All" tab already used (`_all_targets()`/`_merge_all_slots()`/`_aggregate_keys()`) generalizes to run over an arbitrary selected subset instead of only ever "all visible" or "exactly one". Every call site that read/wrote `active_production` (rendering, click handling, keyboard focus, refresh scheduling, the enabled-productions cascade, settings persistence) is updated to the set-based model.

**Tech Stack:** Python 3, tkinter, Pillow (PIL) — no new dependencies.

**Spec:** [docs/superpowers/specs/2026-09-13-multi-select-production-tabs-design.md](../specs/2026-09-13-multi-select-production-tabs-design.md)

## Global Constraints

- `self.selected_productions` is never empty while the widget is running — every removal path refuses to drop the last remaining selected id.
- `ALL_PRODUCTION_ID` (`"__all__"`) is a click target/shortcut only. It is never a member of `self.selected_productions`.
- Clicking the "All" tab selects every currently-visible production if it isn't already the full set; if it already is, the click is a no-op (confirmed with the product owner — this is intentional, not a bug to fix later).
- Every tab (including "All") is a plain-click toggle. No modifier-key (ctrl/shift) behavior.
- The separate "which productions show as a tab at all" checklist (`enabled_productions`, `open_productions_menu()`, the right-click productions submenu) is unchanged except for the one cascade rule in Task 6.
- `selected_productions` is persisted to `settings.json` as a sorted list. The old single-value `"active_production"` key is read once as a migration input (`config.load_legacy_active_production()`) and never written back.
- This repo has no unit tests for `widget.py`, `refresh.py`, `rendering.py`, or `interaction.py` today (they all depend on a live Tk window/PIL image or real network I/O) — only pure-logic modules (`config.py`) and mixins already covered by a lightweight attribute-stub pattern (`GridMixin` via `tests/test_grid_layout.py`/`tests/test_grid_columns.py`) have automated coverage. This plan follows that existing precedent: it adds automated tests wherever a task fits the precedent (config.py, the `GridMixin` band condition, and two mixins — `MenuMixin`/`RefreshMixin` — that fit the same stub recipe but have no test file yet) and relies on the manual verification pass (Task 9, via the `run` skill) for the rest. Do not invent new Tk-mocking infrastructure to force automated coverage onto code this project has never unit-tested.

---

### Task 1: `config.py` — replace the `active_production` setting with `selected_productions`

**Files:**
- Modify: `deskwidget_core/config.py:59-159` (`DEFAULT_SETTINGS`, `load_settings()`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.DEFAULT_SETTINGS["selected_productions"] == []`; `config.load_settings()["selected_productions"]` (list of str, coerced); `config.load_legacy_active_production() -> str | None`, a new module-level function reading the raw `"active_production"` key straight from `settings.json` (bypassing `DEFAULT_SETTINGS`/`load_settings()`'s own dict, since that key is no longer part of either).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (near the existing `enabled_productions` tests):

```python
def test_load_settings_filters_non_string_selected_productions():
    config.SETTINGS_PATH.write_text('{"selected_productions": ["hololive", 1, null, "nijisanji"]}', encoding="utf-8")

    assert config.load_settings()["selected_productions"] == ["hololive", "nijisanji"]


def test_load_settings_selected_productions_defaults_to_empty_when_not_a_list():
    config.SETTINGS_PATH.write_text('{"selected_productions": "hololive"}', encoding="utf-8")

    assert config.load_settings()["selected_productions"] == []


def test_load_legacy_active_production_reads_saved_value():
    config.SETTINGS_PATH.write_text('{"active_production": "nijisanji"}', encoding="utf-8")

    assert config.load_legacy_active_production() == "nijisanji"


@pytest.mark.parametrize("file_contents", ["not json", "{}", '{"active_production": 5}'])
def test_load_legacy_active_production_returns_none_when_missing_or_invalid(file_contents):
    config.SETTINGS_PATH.write_text(file_contents, encoding="utf-8")

    assert config.load_legacy_active_production() is None


def test_load_legacy_active_production_returns_none_when_file_absent():
    assert config.load_legacy_active_production() is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_config.py -k "selected_productions or legacy_active_production" -v`
Expected: FAIL — `KeyError: 'selected_productions'` and `AttributeError: module 'deskwidget_core.config' has no attribute 'load_legacy_active_production'`.

- [ ] **Step 3: Replace the `active_production` default and add a shared list-coercion helper**

In `deskwidget_core/config.py`, replace:

```python
    # Validated against the actually-loaded productions manifest in
    # widget.py (not here) since that's data talents.py owns, not a plain
    # window/UI preference like everything else in this file.
    "active_production": "hololive",
    # Which productions show as tabs. Empty here means "no preference saved
    # yet" -- widget.py treats that (and any list left with nothing valid
    # after being checked against the loaded manifest) as "show everything",
    # so a first run or a stale/edited list never hides every tab.
    "enabled_productions": [],
```

with:

```python
    # Which productions show as tabs. Empty here means "no preference saved
    # yet" -- widget.py treats that (and any list left with nothing valid
    # after being checked against the loaded manifest) as "show everything",
    # so a first run or a stale/edited list never hides every tab.
    "enabled_productions": [],
    # Which of the shown tabs are toggled on right now (multi-select; the
    # merged view is whatever this set adds up to). Empty here means "no
    # preference saved yet" -- same convention as enabled_productions above --
    # and is resolved in widget.py._load_settings(), which also consults
    # load_legacy_active_production() below for a settings.json saved before
    # this list existed. Validated against the loaded manifest in widget.py,
    # not here, same reasoning as enabled_productions.
    "selected_productions": [],
```

Then replace the two nearly-identical list-of-strings coercions:

```python
    settings["active_production"] = _coerce(
        settings["active_production"], DEFAULT_SETTINGS["active_production"], str)
    raw_enabled = settings["enabled_productions"]
    settings["enabled_productions"] = (
        [entry for entry in raw_enabled if isinstance(entry, str)]
        if isinstance(raw_enabled, list) else [])
    return settings
```

with a shared helper, used for both fields:

```python
    settings["enabled_productions"] = _coerce_string_list(settings["enabled_productions"])
    settings["selected_productions"] = _coerce_string_list(settings["selected_productions"])
    return settings


def load_legacy_active_production():
    """One-off migration read for widget.py: a settings.json saved before
    the multi-select production tabs feature stored a single
    "active_production" key (a production id, or the "__all__" pseudo-id).
    That key is no longer part of DEFAULT_SETTINGS/load_settings()'s own
    return value -- this reads it directly, once, so an upgrading user's
    prior single-tab choice can seed their new selected_productions instead
    of silently resetting to the first loaded production."""
    data = load_json(SETTINGS_PATH, {})
    value = data.get("active_production") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None
```

and add the helper itself above `load_settings()`, next to the other `_coerce*` helpers:

```python
def _coerce_string_list(value):
    return [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all tests, including the pre-existing ones — `test_load_settings_returns_defaults_when_file_missing` still passes because `load_settings()`'s returned dict shape is unchanged, just with `selected_productions` instead of `active_production`, and `load_legacy_active_production()` is a separate function that doesn't touch that dict at all).

- [ ] **Step 5: Commit**

```bash
git add deskwidget_core/config.py tests/test_config.py
git commit -m "config: replace single active_production setting with a multi-select list"
```

---

### Task 2: `widget.py` — selection-scoped merge helpers and data properties

**Files:**
- Modify: `deskwidget_core/widget.py:241-250` (`_tray_tooltip_text`), `:331-417` (`_aggregate_keys`/`_merge_all_slots`/`_all_targets`/the five data properties)

**Interfaces:**
- Consumes: nothing new yet — `self.selected_productions` is introduced in Task 3, but this task can be written and reasoned about independently since every function it touches only ever *reads* that attribute (never mutates it). Until Task 3 lands, `self.selected_productions` doesn't exist yet, so this task alone would raise `AttributeError` at runtime — that's fine, Task 3 (same PR-sized unit of work, next commit) supplies it. Both tasks must land together before the app is run.
- Produces: `self._selected_productions_list() -> list[dict]`, `self._aggregate_keys(productions) -> dict`, `self._merge_slots(productions, key) -> dict`, `self._selected_targets() -> list[tuple]`, all consumed by Task 3's properties and by Task 4 (grid_layout.py's band condition).

No automated test for this task — see the Global Constraints note on why `widget.py` has no unit-test harness in this repo. Verified manually in Task 9.

- [ ] **Step 1: Add `_selected_productions_list()` and rewrite the aggregate/merge helpers to take an explicit production list**

In `deskwidget_core/widget.py`, replace:

```python
    def _aggregate_keys(self):
        # Talent names aren't unique *across* productions (e.g. a custom.json
        # entry sharing a name with a talent in another enabled production),
        # but self.states/self.live_urls/self.channel_urls/self.live_titles
        # and the tuples _all_targets() returns are both keyed by plain name.
        # Disambiguate every name beyond the first production that uses it
        # with its production id, so _merge_all_slots() and _all_targets()
        # agree on one key per talent instead of two same-named talents from
        # different productions silently overwriting each other's merged
        # state/URLs (and open_target() misdirecting a click on one talent to
        # the other's live stream/channel).
        seen = {}
        keys = {}
        for production in self._visible_productions():
            slot = self._production_slot(production["id"])
            for name, _slug, _url, _unit in slot["targets"]:
                count = seen.get(name, 0)
                seen[name] = count + 1
                keys[(production["id"], name)] = name if count == 0 else f"{name} ({production['id']})"
        return keys

    def _merge_all_slots(self, key):
        # Dict fields (states/channel_urls/live_urls/live_titles) merged
        # fresh on every access rather than cached, so this always reflects
        # whatever the per-production refresh threads have written into
        # self.production_data[prod_id] directly (see the note below) instead
        # of a stale snapshot from whenever the "All" tab was last entered.
        aggregate_keys = self._aggregate_keys()
        merged = {}
        for production in self._visible_productions():
            slot = self._production_slot(production["id"])
            with slot["lock"]:
                slot_values = dict(slot[key])
            for name, value in slot_values.items():
                merged[aggregate_keys[(production["id"], name)]] = value
        return merged

    def _all_targets(self):
        # Retags each talent's unit with its own production's display name,
        # so build_grid_layout()'s per-unit grouping renders one category per
        # production here instead of merging same-named units (e.g. "JP")
        # across different productions into one section.
        aggregate_keys = self._aggregate_keys()
        targets = []
        for production in self._visible_productions():
            label = production_display_name(production, self.lang)
            slot = self._production_slot(production["id"])
            targets.extend((aggregate_keys[(production["id"], name)], slug, url, label)
                            for name, slug, url, _unit in slot["targets"])
        return targets
```

with:

```python
    def _selected_productions_list(self):
        # self._visible_productions() filtered down to the ones currently
        # toggled on in the tab strip (see toggle_production_selection()) --
        # what the merged view (targets/states/channel_urls/live_urls/
        # live_titles below) actually aggregates, and what refresh.py refreshes.
        return [p for p in self._visible_productions() if p["id"] in self.selected_productions]

    def _aggregate_keys(self, productions):
        # Talent names aren't unique *across* productions (e.g. a custom.json
        # entry sharing a name with a talent in another enabled production),
        # but self.states/self.live_urls/self.channel_urls/self.live_titles
        # and the tuples _selected_targets() returns are both keyed by plain
        # name. Disambiguate every name beyond the first production (within
        # `productions`, in order) that uses it with its production id, so
        # _merge_slots() and _selected_targets() agree on one key per talent
        # instead of two same-named talents from different productions
        # silently overwriting each other's merged state/URLs (and
        # open_target() misdirecting a click on one talent to the other's
        # live stream/channel).
        seen = {}
        keys = {}
        for production in productions:
            slot = self._production_slot(production["id"])
            for name, _slug, _url, _unit in slot["targets"]:
                count = seen.get(name, 0)
                seen[name] = count + 1
                keys[(production["id"], name)] = name if count == 0 else f"{name} ({production['id']})"
        return keys

    def _merge_slots(self, productions, key):
        # Dict fields (states/channel_urls/live_urls/live_titles) merged
        # fresh on every access rather than cached, so this always reflects
        # whatever the per-production refresh threads have written into
        # self.production_data[prod_id] directly (see the note below) instead
        # of a stale snapshot from whenever `productions` was last read.
        # Takes an explicit production list rather than reading
        # self._selected_productions_list() itself: _tray_tooltip_text()
        # needs to merge over every *visible* production regardless of the
        # current selection (a global "how much is live" glance, not tied to
        # whatever tab happens to be showing), while the states/channel_urls/
        # live_urls/live_titles properties below need the *selected* subset.
        aggregate_keys = self._aggregate_keys(productions)
        merged = {}
        for production in productions:
            slot = self._production_slot(production["id"])
            with slot["lock"]:
                slot_values = dict(slot[key])
            for name, value in slot_values.items():
                merged[aggregate_keys[(production["id"], name)]] = value
        return merged

    def _selected_targets(self):
        # Exactly one selected production keeps that production's own
        # internal sub-grouping (e.g. "JP"/"ID"/"EN") untouched -- the same
        # single-slot fast path the old single-tab view used. Two or more
        # retags each talent's unit with its own production's display name
        # instead, so build_grid_layout()'s per-unit grouping renders one
        # category per production (see the shaded "band" it draws for that
        # case) rather than merging same-named units across productions
        # into one section.
        selected = self._selected_productions_list()
        if len(selected) == 1:
            return self._production_slot(selected[0]["id"])["targets"]
        aggregate_keys = self._aggregate_keys(selected)
        targets = []
        for production in selected:
            label = production_display_name(production, self.lang)
            slot = self._production_slot(production["id"])
            targets.extend((aggregate_keys[(production["id"], name)], slug, url, label)
                            for name, slug, url, _unit in slot["targets"])
        return targets
```

- [ ] **Step 2: Update the five data properties and the tray tooltip to use the new helpers**

Replace:

```python
    # These five reflect whichever production is active_production right
    # now, for every part of the app (rendering, click handling, tooltips,
    # open_target) that only ever cares about "what's currently on screen".
    # When active_production is ALL_PRODUCTION_ID they instead merge every
    # real production's data on the fly (see _all_targets()/_merge_all_slots()
    # above). The refresh machinery (refresh/refresh_worker/check_one)
    # instead threads an explicit prod_id through and reads/writes
    # self.production_data[prod_id] directly, so a background refresh
    # started before a tab switch can never write into the wrong tab's data
    # once the user has switched away from it.
    @property
    def targets(self):
        if self.active_production == ALL_PRODUCTION_ID:
            return self._all_targets()
        return self._production_slot(self.active_production)["targets"]

    def _slot_field(self, key):
        if self.active_production == ALL_PRODUCTION_ID:
            return self._merge_all_slots(key)
        return self._production_slot(self.active_production)[key]
```

with:

```python
    # These five reflect whichever productions are currently selected in the
    # tab strip (self.selected_productions -- see
    # toggle_production_selection()), for every part of the app (rendering,
    # click handling, tooltips, open_target) that only ever cares about
    # "what's currently on screen". _selected_targets()/_merge_slots() above
    # handle the one-selected-production case the same way a direct slot
    # read used to. The refresh machinery (refresh/refresh_worker/check_one)
    # instead threads an explicit prod_id through and reads/writes
    # self.production_data[prod_id] directly, so a background refresh
    # started before a selection change can never write into the wrong
    # slot's data once the user has changed the selection.
    @property
    def targets(self):
        return self._selected_targets()

    def _slot_field(self, key):
        return self._merge_slots(self._selected_productions_list(), key)
```

(The `states`/`channel_urls`/`live_urls`/`live_titles` properties directly below `_slot_field` are unchanged — they already just call `self._slot_field(...)`.)

Replace `_tray_tooltip_text()`'s body:

```python
    def _tray_tooltip_text(self):
        # Reuses _merge_all_slots() (rather than hand-rolling the same merge)
        # so this stays under the same per-slot lock that guards it against
        # check_one()'s background threads -- see the "lock" note in
        # _production_slot().
        merged_states = self._merge_all_slots("states")
```

with:

```python
    def _tray_tooltip_text(self):
        # Reuses _merge_slots() (rather than hand-rolling the same merge) so
        # this stays under the same per-slot lock that guards it against
        # check_one()'s background threads -- see the "lock" note in
        # _production_slot(). Merges over every *visible* production, not
        # just the currently selected ones: this is a global "how much is
        # live across everything enabled" glance, independent of whatever
        # tab happens to be showing.
        merged_states = self._merge_slots(self._visible_productions(), "states")
```

- [ ] **Step 3: Fix three other comments in `widget.py` that reference the old names**

These are outside the blocks Steps 1-2 already replaced, so they're easy to miss —
find them with `grep -n "active_production\|_all_targets\|_merge_all_slots" deskwidget_core/widget.py`.

In `__init__` (near `self.production_data = {}`), replace:

```python
        # self.targets/states/channel_urls/live_urls/live_titles below are
        # properties reading whichever slot is active_production right now.
        self.production_data = {}
```

with:

```python
        # self.targets/states/channel_urls/live_urls/live_titles below are
        # properties merging whichever slots are currently selected (see
        # selected_productions/toggle_production_selection()).
        self.production_data = {}
```

In `_production_slot()`'s slot-dict literal, replace:

```python
                # Guards every write into the four dict fields above from
                # check_one()'s background threads against _merge_all_slots()
                # reading/merging them on the Tk main thread -- without this,
```

with:

```python
                # Guards every write into the four dict fields above from
                # check_one()'s background threads against _merge_slots()
                # reading/merging them on the Tk main thread -- without this,
```

In `_valid_production_ids()`, replace:

```python
        # hand-edited settings.json shouldn't be able to switch into it either;
        # _all_targets() would otherwise collapse that production's own
        # per-unit grouping into one section while render() still draws the
```

with:

```python
        # hand-edited settings.json shouldn't be able to switch into it either;
        # _selected_targets() would otherwise collapse that production's own
        # per-unit grouping into one section while render() still draws the
```

- [ ] **Step 4: Sanity-check for lingering references to the old names**

Run: `grep -rn "_all_targets\|_merge_all_slots\|_aggregate_keys()" deskwidget_core/`
Expected: no matches (the only remaining `_aggregate_keys(` calls take an argument now, from this task's own new code).

- [ ] **Step 5: Commit**

```bash
git add deskwidget_core/widget.py
git commit -m "widget: scope the production merge helpers to the selected set, not just All"
```

---

### Task 3: `widget.py` — `toggle_production_selection()` and settings load/save

**Files:**
- Modify: `deskwidget_core/widget.py:73-100` (`_load_settings`), `:446-459` (`switch_production`), `:658-686` (`current_settings`)

**Interfaces:**
- Consumes: `config.load_legacy_active_production()` (Task 1), `self._selected_productions_list()`/`self._merge_slots()`/`self._selected_targets()` (Task 2).
- Produces: `self.selected_productions: set[str]` (the attribute Task 2's helpers read), `self.toggle_production_selection(prod_id)`, consumed by Task 4 (`grid_layout.py` focusable_items) and Task 7 (`interaction.py` click). Task 6 (`menus.py`'s cascade) enforces the same never-empty invariant but mutates `self.selected_productions` directly rather than calling this method.

No automated test for this task — see the Global Constraints note. Verified manually in Task 9.

- [ ] **Step 1: Replace `active_production` in `_load_settings()` with the resolved `selected_productions` set**

Replace:

```python
        self.active_production = (settings["active_production"]
            if settings["active_production"] in self._valid_production_ids()
            else self.productions[0]["id"])
        # Which productions show as tabs (and count toward the "All" tab).
        # Falls back to every loaded production whenever the saved list is
        # empty or has nothing left that matches the current manifest, so a
        # first run (or one where a production was since removed) never
        # starts with an empty tab strip.
        valid_ids = {p["id"] for p in self.productions}
        saved_enabled = [pid for pid in settings["enabled_productions"] if pid in valid_ids]
        self.enabled_productions = set(saved_enabled) if saved_enabled else set(valid_ids)
```

with:

```python
        # Which productions show as tabs (and count toward the "All" tab).
        # Falls back to every loaded production whenever the saved list is
        # empty or has nothing left that matches the current manifest, so a
        # first run (or one where a production was since removed) never
        # starts with an empty tab strip.
        valid_ids = {p["id"] for p in self.productions}
        saved_enabled = [pid for pid in settings["enabled_productions"] if pid in valid_ids]
        self.enabled_productions = set(saved_enabled) if saved_enabled else set(valid_ids)
        # Which of the shown tabs are toggled on (multi-select -- see
        # toggle_production_selection()). Resolution order: (1) the saved
        # list, filtered to ids that still exist; (2) a settings.json saved
        # before this list existed, via its single "active_production" value
        # (the "__all__" pseudo-id there means "everything visible"); (3) the
        # first loaded production, same last-resort as the old
        # active_production fallback. Never left empty, same "never start
        # with nothing shown" reasoning as enabled_productions above.
        saved_selected = [pid for pid in settings["selected_productions"] if pid in valid_ids]
        if saved_selected:
            self.selected_productions = set(saved_selected)
        else:
            legacy = load_legacy_active_production()
            if legacy == ALL_PRODUCTION_ID:
                self.selected_productions = set(self.enabled_productions)
            elif legacy in valid_ids:
                self.selected_productions = {legacy}
            else:
                self.selected_productions = {self.productions[0]["id"]}
```

Add `load_legacy_active_production` to the `from .config import (...)` block near the top of `widget.py`:

```python
from .config import (
    DEFAULT_HEIGHT,
    DEFAULT_SETTINGS,
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    MIN_WINDOW_ALPHA,
    load_legacy_active_production,
    load_settings,
    save_settings,
)
```

- [ ] **Step 2: Replace `switch_production()` with `toggle_production_selection()`**

Replace:

```python
    def switch_production(self, prod_id):
        if prod_id == self.active_production or prod_id not in self._valid_production_ids():
            return
        self.active_production = prod_id
        if prod_id == ALL_PRODUCTION_ID:
            for production in self._visible_productions():
                self._production_slot(production["id"])
        else:
            self._production_slot(prod_id)
        self.focus_index = None
        if self.live_only:
            self.fit_height()
        self.request_render()
        self.refresh()
```

with:

```python
    def toggle_production_selection(self, prod_id):
        # Real production tab: toggle its membership in the selection.
        # Adding is always allowed; removing is refused (no-op) if it's the
        # only one currently selected (see the "never empty" invariant in
        # the design doc). "All": select every currently-visible production
        # if that isn't already the full selection; if it already is, do
        # nothing -- a deliberate consequence of that same invariant (there's
        # no way to "deselect all" without leaving zero selected), not a bug.
        if prod_id == ALL_PRODUCTION_ID:
            visible_ids = {p["id"] for p in self._visible_productions()}
            if self.selected_productions == visible_ids:
                return
            self.selected_productions = set(visible_ids)
            for production in self._visible_productions():
                self._production_slot(production["id"])
        else:
            if prod_id not in self._productions_by_id:
                return
            if prod_id in self.selected_productions:
                if len(self.selected_productions) <= 1:
                    return
                self.selected_productions.discard(prod_id)
            else:
                self.selected_productions.add(prod_id)
                self._production_slot(prod_id)
        self.focus_index = None
        if self.live_only:
            self.fit_height()
        self.request_render()
        self.refresh()
```

`_valid_production_ids()` (a few lines above `_production_slot()`) is still used by the legacy-migration check added in Step 1 above, so leave it in place.

- [ ] **Step 3: Update `current_settings()` to persist `selected_productions` instead of `active_production`**

Replace:

```python
            "active_production": self.active_production,
            "enabled_productions": [p["id"] for p in self.productions if p["id"] in self.enabled_productions],
```

with:

```python
            "selected_productions": sorted(
                p["id"] for p in self.productions if p["id"] in self.selected_productions),
            "enabled_productions": [p["id"] for p in self.productions if p["id"] in self.enabled_productions],
```

(`sorted(...)` over `self.productions`-order ids, not `sorted(self.selected_productions)` directly, so the saved list is deterministic string order — either is fine functionally since `_load_settings()` re-derives a `set` on load either way, but sorting keeps `settings.json` diffs stable across saves, matching this codebase's general care about deterministic persisted output.)

- [ ] **Step 4: Sanity-check for lingering references to `active_production`/`switch_production`**

Run: `grep -rn "active_production\|switch_production" deskwidget_core/`
Expected: no matches yet in `widget.py` itself; Tasks 4-7 still need to update `grid_layout.py`, `rendering.py`, `interaction.py`, and `menus.py`, so matches there are expected until those tasks land.

- [ ] **Step 5: Commit**

```bash
git add deskwidget_core/widget.py
git commit -m "widget: add toggle_production_selection() and migrate settings load/save"
```

---

### Task 4: `grid_layout.py` — per-production band condition and keyboard wiring

**Files:**
- Modify: `deskwidget_core/grid_layout.py:570` (band condition in `_layout_talent_section()` — the method containing the `if self.active_production == ALL_PRODUCTION_ID:` block), `:965-967` (`focusable_items()`'s tab activation)
- Test: `tests/test_grid_columns.py`

**Interfaces:**
- Consumes: `self._selected_productions_list()` (Task 2), `self.toggle_production_selection` (Task 3).

- [ ] **Step 1: Write the failing test**

In `tests/test_grid_columns.py`, the `FakeGrid` stub currently has `self.active_production = "test"` purely so the band condition (which this task is about to change) has something to read. Add a new test that exercises the band condition directly through `FakeGrid`, and update the stub to match the new interface:

Replace, in `FakeGrid.__init__`:

```python
        self.active_production = "test"
```

with:

```python
        self._selected = [{"id": "test"}]
```

Add a method to `FakeGrid` (anywhere among its other small helper methods, e.g. right after `has_multiple_productions`):

```python
    def _selected_productions_list(self):
        return self._selected
```

Add a new test near the bottom of `tests/test_grid_columns.py`:

```python
def test_single_selected_production_draws_no_band():
    grid = FakeGrid(talents=6)

    layout_items, _row_height, _divider_height, _scale = grid.compute_grid()

    assert not any(item["type"] == "band" for item in layout_items)


def test_multiple_selected_productions_draws_a_band_per_unit():
    grid = FakeGrid(talents=6)
    grid._selected = [{"id": "prod-a"}, {"id": "prod-b"}]

    layout_items, _row_height, _divider_height, _scale = grid.compute_grid()

    assert any(item["type"] == "band" for item in layout_items)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_grid_columns.py -k band -v`
Expected: `test_single_selected_production_draws_no_band` passes already (band condition today reads `self.active_production == ALL_PRODUCTION_ID`, and `FakeGrid` doesn't set that to `"__all__"`, so no band is drawn — that's the point, it's a regression guard). `test_multiple_selected_productions_draws_a_band_per_unit` FAILS: still no band, since the current condition doesn't know about `_selected_productions_list()` yet.

- [ ] **Step 3: Update the band condition**

In `deskwidget_core/grid_layout.py`, replace:

```python
            if self.active_production == ALL_PRODUCTION_ID:
                layout_items.insert(band_index, {"type": "band", "y": band_start_y,
                                                  "h": y - band_start_y, "position": group_position})
                group_position += 1
```

with:

```python
            if len(self._selected_productions_list()) > 1:
                layout_items.insert(band_index, {"type": "band", "y": band_start_y,
                                                  "h": y - band_start_y, "position": group_position})
                group_position += 1
```

Remove the now-unused `ALL_PRODUCTION_ID` import at the top of the file if `production_display_name` is the only other thing imported from `.talents`:

```python
from .talents import ALL_PRODUCTION_ID, production_display_name
```

becomes:

```python
from .talents import production_display_name
```

(Check first with `grep -n "ALL_PRODUCTION_ID" deskwidget_core/grid_layout.py` — it should show only the import line and the line just deleted above.)

Also update every other comment that references the old condition/helper name
(purely explanatory, no behavior change) — run `grep -n "_all_targets\|_merge_all_slots\|active_production"
deskwidget_core/grid_layout.py` to find all of them; six remain after the edits
above. (`production_tabs()`'s own docstring mentions of the "All" tab, near the top
of the file, are still accurate as-is — that tab still exists as a click target — so
leave those alone.)

In `_layout_talent_section()`'s docstring, replace:

```python
        # Appends each unit's divider/rows (and, on the "All" tab, its
        # shaded background band) to layout_items and returns the y
        # position just below the talent grid.
```

with:

```python
        # Appends each unit's divider/rows (and, when more than one
        # production is selected, its shaded background band) to
        # layout_items and returns the y position just below the talent grid.
```

A few lines later, in the same method's per-unit loop, replace:

```python
            # On the "All" tab each unit is a whole production (see
            # _all_targets()'s retagging), so its rows get a shaded background
            # band -- the divider text alone was too easy to miss when
```

with:

```python
            # With more than one production selected, each unit is a whole
            # production (see _selected_targets()'s retagging), so its rows
            # get a shaded background band -- the divider text alone was too
            # easy to miss when
```

In `build_grid_layout()`, replace:

```python
        # Read the targets/states properties once up front rather than once
        # per loop iteration -- for the "All" tab (active_production ==
        # ALL_PRODUCTION_ID) each read re-merges every visible production's
        # dict from scratch (see _merge_all_slots()), so calling it inside
```

with:

```python
        # Read the targets/states properties once up front rather than once
        # per loop iteration -- merging more than one selected production
        # (see _selected_productions_list()) re-merges every one of their
        # dicts from scratch (see _merge_slots()), so calling it inside
```

A little further down in the same method, replace:

```python
        # Only consulted while a title query is active (see row_visible()),
        # and render()/compute_grid() only ever merge live_titles when the
        # title view is on -- so this default never costs a "All"-tab merge
        # on the plain grid view, where no row's visibility depends on it.
```

with:

```python
        # Only consulted while a title query is active (see row_visible()),
        # and render()/compute_grid() only ever merge live_titles when the
        # title view is on -- so this default never costs a multi-production
        # merge on the plain grid view, where no row's visibility depends on it.
```

In `compute_grid()`, replace:

```python
        # Merged once here rather than left for each measure() candidate's
        # build_grid_layout() call to re-fetch: on the "All" tab, self.targets
        # /self.states each re-merge every visible production's dict from
        # scratch (see _merge_all_slots()), so leaving that inside the
```

with:

```python
        # Merged once here rather than left for each measure() candidate's
        # build_grid_layout() call to re-fetch: with more than one production
        # selected, self.targets/self.states each re-merge every one of their
        # dicts from scratch (see _merge_slots()), so leaving that inside the
```

In `focusable_items()`'s docstring, replace:

```python
        # redundant compute_grid() pass -- or, on the "All" tab, a second
        # self.targets re-merge (see _merge_all_slots()) -- on every render,
```

with:

```python
        # redundant compute_grid() pass -- or, when more than one production
        # is selected, a second self.targets re-merge (see _merge_slots()) --
        # on every render,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_grid_columns.py -v`
Expected: PASS (all tests in the file, including every pre-existing one — `FakeGrid`'s other tests never touched `active_production`/`_selected_productions_list` and are unaffected).

- [ ] **Step 5: Update keyboard focus wiring**

In `deskwidget_core/grid_layout.py`'s `focusable_items()`, replace:

```python
        for tab in self.production_tabs():
            items.append({"kind": "tab", "rect": tab["rect"],
                         "activate": lambda t=tab["id"]: self.switch_production(t)})
```

with:

```python
        for tab in self.production_tabs():
            items.append({"kind": "tab", "rect": tab["rect"],
                         "activate": lambda t=tab["id"]: self.toggle_production_selection(t)})
```

No test for this — `focusable_items()`'s tab-activation callback isn't exercised anywhere in the test suite today (it requires a real `LayeredWidget`). Verified manually in Task 9 (keyboard Tab to a production tab, press Enter/Space, confirm it toggles that tab like a mouse click does).

- [ ] **Step 6: Commit**

```bash
git add deskwidget_core/grid_layout.py tests/test_grid_columns.py
git commit -m "grid_layout: band multiple selected productions, not just the All tab"
```

---

### Task 5: `rendering.py` — tab highlight for multiple selections

**Files:**
- Modify: `deskwidget_core/rendering.py:150-165` (`_draw_tabs`)

**Interfaces:**
- Consumes: `self.selected_productions` (Task 3), `self._visible_productions()` (existing).

No automated test for this task (`rendering.py` draws into a real PIL image via a live Tk window — no test file exists for it in this repo). Verified manually in Task 9.

- [ ] **Step 1: Update the `active` check**

In `deskwidget_core/rendering.py`, replace:

```python
    def _draw_tabs(self, draw, colors, accent):
        tabs = self.production_tabs()
        for tab in tabs:
            rect = tab["rect"]
            active = tab["id"] == self.active_production
```

with:

```python
    def _draw_tabs(self, draw, colors, accent):
        tabs = self.production_tabs()
        all_visible_selected = (
            {p["id"] for p in self._visible_productions()} == self.selected_productions)
        for tab in tabs:
            rect = tab["rect"]
            active = (all_visible_selected if tab["id"] == ALL_PRODUCTION_ID
                      else tab["id"] in self.selected_productions)
```

`rendering.py` doesn't import anything from `.talents` yet (it currently imports
`production_band_color` from `.theme`, a different module — don't confuse the two).
Add a new import line for it, alongside the other `from .x import ...` lines near the
top of the file (after `from .strings import STRINGS, english_name`):

```python
from .talents import ALL_PRODUCTION_ID
```

- [ ] **Step 2: Fix three other comments in `rendering.py` that reference the old names**

Find them with `grep -n "active_production\|_merge_all_slots" deskwidget_core/rendering.py`
(purely explanatory, no behavior change). In `render()`, replace:

```python
        # Read once up front, not per access below -- for the "All" tab
        # (active_production == ALL_PRODUCTION_ID) each of these properties
        # re-merges every visible production's dict from scratch (see
        # _merge_all_slots()), so repeating self.targets/self.states/
```

with:

```python
        # Read once up front, not per access below -- merging more than one
        # selected production, each of these properties re-merges every
        # one of their dicts from scratch (see _merge_slots()), so
        # repeating self.targets/self.states/
```

In `_draw_grid_rows()`, replace:

```python
        # live_titles is threaded through too, not just targets/states: on the
        # "All" tab it is another _merge_all_slots() pass, and compute_grid()
        # needs it to apply the title filter -- letting it re-merge here would
```

with:

```python
        # live_titles is threaded through too, not just targets/states: with
        # more than one production selected it is another _merge_slots() pass,
        # and compute_grid() needs it to apply the title filter -- letting it
        # re-merge here would
```

- [ ] **Step 3: Sanity-check the rest of the file for stale references**

Run: `grep -n "active_production\|_all_targets\|_merge_all_slots" deskwidget_core/rendering.py`
Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add deskwidget_core/rendering.py
git commit -m "rendering: highlight every selected production tab, not just one"
```

---

### Task 6: `menus.py` — cascade selection when a production is disabled

**Files:**
- Modify: `deskwidget_core/menus.py:333-356` (`toggle_production`/`set_production_enabled`), imports at the top of the file
- Test: `tests/test_menus.py` (new file)

**Interfaces:**
- Consumes: `self.selected_productions` (Task 3), `self._visible_productions()`/`self._production_slot()` (existing).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_menus.py`:

```python
"""MenuMixin's production enable/disable cascade: disabling a production
that's part of the current multi-select must also drop it from the
selection, falling back to "select everything still visible" if that would
otherwise empty the selection -- the same "never leave the merged view with
nothing selected" invariant the tab strip itself enforces. Driven through a
stub carrying only the handful of attributes this cascade reads, so no Tk
window is needed (mirrors the FakeGrid/FakeWidget pattern already used for
GridMixin in tests/test_grid_columns.py and tests/test_grid_layout.py)."""
from deskwidget_core.menus import MenuMixin


class FakeMenu(MenuMixin):
    def __init__(self, production_ids, enabled, selected):
        self.productions = [{"id": pid} for pid in production_ids]
        self.enabled_productions = set(enabled)
        self.selected_productions = set(selected)
        self.production_data = {}
        self.render_calls = 0

    def _visible_productions(self):
        return [p for p in self.productions if p["id"] in self.enabled_productions]

    def _production_slot(self, prod_id):
        return self.production_data.setdefault(prod_id, {"targets": []})

    def render(self):
        self.render_calls += 1


def test_disabling_a_production_outside_the_selection_leaves_selection_untouched():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a"])

    assert menu.set_production_enabled("b", False) is True
    assert menu.selected_productions == {"a"}
    assert menu.enabled_productions == {"a", "c"}


def test_disabling_one_of_several_selected_productions_just_drops_it():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a", "b"])

    menu.set_production_enabled("b", False)

    assert menu.selected_productions == {"a"}


def test_disabling_the_only_selected_production_falls_back_to_everything_visible():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["b"])

    menu.set_production_enabled("b", False)

    assert menu.selected_productions == {"a", "c"}
    # Both remaining visible productions get a slot pre-created, same as the
    # old switch_production(ALL_PRODUCTION_ID) fallback used to.
    assert set(menu.production_data) == {"a", "c"}


def test_disabling_the_last_visible_production_is_refused():
    menu = FakeMenu(["a"], enabled=["a"], selected=["a"])

    assert menu.set_production_enabled("a", False) is False
    assert menu.enabled_productions == {"a"}
    assert menu.selected_productions == {"a"}


def test_enabling_a_production_does_not_add_it_to_the_selection():
    menu = FakeMenu(["a", "b"], enabled=["a"], selected=["a"])

    menu.set_production_enabled("b", True)

    assert menu.enabled_productions == {"a", "b"}
    assert menu.selected_productions == {"a"}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_menus.py -v`
Expected: FAIL — `set_production_enabled()` today never touches `selected_productions` (it still reads/writes the old `active_production`), so `test_disabling_the_only_selected_production_falls_back_to_everything_visible` and `test_enabling_a_production_does_not_add_it_to_the_selection` fail their assertions; the others may pass incidentally but re-run after Step 3 to confirm all five are exercised meaningfully.

- [ ] **Step 3: Update `set_production_enabled()` and drop the now-unused `toggle_production()`/import references**

Replace:

```python
    def toggle_production(self, prod_id):
        # Used by show_context_menu()'s per-production entries, which (unlike
        # open_productions_menu()'s checkboxes) have no widget state of their
        # own to read back -- toggling off the last visible production is
        # simply a no-op here, same guard as set_production_enabled().
        self.set_production_enabled(prod_id, prod_id not in self.enabled_productions)

    def set_production_enabled(self, prod_id, enabled):
        if enabled:
            self.enabled_productions.add(prod_id)
            if self.active_production == ALL_PRODUCTION_ID:
                # Mirrors switch_production()'s ALL_PRODUCTION_ID branch: a
                # production just re-added to the "All" view needs its slot
                # created up front (on this, the main thread), not lazily
                # from refresh_worker()'s background thread.
                self._production_slot(prod_id)
        else:
            if len(self.enabled_productions) <= 1:
                return False
            self.enabled_productions.discard(prod_id)
            if self.active_production == prod_id:
                self.switch_production(ALL_PRODUCTION_ID)
        self.render()
        return True
```

with:

```python
    def toggle_production(self, prod_id):
        # Used by show_context_menu()'s per-production entries, which (unlike
        # open_productions_menu()'s checkboxes) have no widget state of their
        # own to read back -- toggling off the last visible production is
        # simply a no-op here, same guard as set_production_enabled().
        self.set_production_enabled(prod_id, prod_id not in self.enabled_productions)

    def set_production_enabled(self, prod_id, enabled):
        if enabled:
            self.enabled_productions.add(prod_id)
            # No slot pre-creation needed here any more: a newly re-enabled
            # production starts deselected (see toggle_production_selection
            # in widget.py), so its slot is created lazily whenever it's
            # actually selected.
        else:
            if len(self.enabled_productions) <= 1:
                return False
            self.enabled_productions.discard(prod_id)
            if prod_id in self.selected_productions:
                self.selected_productions.discard(prod_id)
                if not self.selected_productions:
                    # The disabled production was the only one selected --
                    # fall back to the merged view over everything still
                    # visible, the same fallback switch_production(
                    # ALL_PRODUCTION_ID) used to provide when the single
                    # active production was disabled.
                    self.selected_productions = {p["id"] for p in self._visible_productions()}
                    for production in self._visible_productions():
                        self._production_slot(production["id"])
        self.render()
        return True
```

Remove the now-unused `ALL_PRODUCTION_ID` import at the top of `menus.py`:

```python
from .talents import ALL_PRODUCTION_ID, production_display_name
```

becomes:

```python
from .talents import production_display_name
```

(Confirm first with `grep -n "ALL_PRODUCTION_ID" deskwidget_core/menus.py` — after this edit it should show no matches.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_menus.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add deskwidget_core/menus.py tests/test_menus.py
git commit -m "menus: cascade the enabled-productions checklist into the selection"
```

---

### Task 7: `interaction.py` — click wiring

**Files:**
- Modify: `deskwidget_core/interaction.py:267-268` (`click()`'s tab-hit branch)

**Interfaces:**
- Consumes: `self.toggle_production_selection` (Task 3).

No automated test for this task (`click()` is exercised only through a real Tk `<Button-1>` event in the running app; `tests/test_interaction.py` covers unrelated drag-threshold logic and never touches production tabs). Verified manually in Task 9.

- [ ] **Step 1: Update the tab-hit branch**

In `deskwidget_core/interaction.py`, replace:

```python
        elif hit_tab is not None:
            self.switch_production(hit_tab["id"])
```

with:

```python
        elif hit_tab is not None:
            self.toggle_production_selection(hit_tab["id"])
```

- [ ] **Step 2: Sanity-check for lingering references**

Run: `grep -rn "active_production\|switch_production\|_all_targets\|_merge_all_slots" deskwidget_core/`
Expected: no matches anywhere in `deskwidget_core/` (Tasks 1-7 have now touched every call site the design doc identified).

- [ ] **Step 3: Commit**

```bash
git add deskwidget_core/interaction.py
git commit -m "interaction: clicking a production tab toggles its selection"
```

---

### Task 8: `refresh.py` — refresh the selected set, not a single active id

**Files:**
- Modify: `deskwidget_core/refresh.py:72-158` (`refresh`, `refresh_worker`, `refresh_complete`), imports at the top of the file
- Test: `tests/test_refresh.py` (new file, `refresh_complete()`'s staleness branch only)

**Interfaces:**
- Consumes: `self.selected_productions` (Task 3).

- [ ] **Step 1: Write the failing test**

`refresh_worker()`/`check_one()` do real threading and network I/O and have never been unit-tested in this repo; this task only adds coverage for `refresh_complete()`'s pure "is this result still current" branch, using the same stub-a-mixin recipe as Task 6.

Create `tests/test_refresh.py`:

```python
"""RefreshMixin.refresh_complete()'s staleness check: a refresh started for
one selection must not clobber last_updated/reschedule the periodic timer if
the user changed the selection while it was still in flight -- it should
instead kick an immediate refresh for whatever's selected now. Driven
through a stub (mirrors tests/test_menus.py's FakeMenu) rather than a real
widget, since refresh_worker()/check_one() do real threading and network
I/O that this repo has never unit-tested and this task isn't changing."""
from deskwidget_core.refresh import RefreshMixin


class FakeRefresh(RefreshMixin):
    def __init__(self, selected):
        self.selected_productions = set(selected)
        self.refresh_in_progress = True
        self.tray = None
        self.last_updated = None
        self.render_calls = 0
        self.refresh_calls = 0
        self.rescheduled = []

    def render(self):
        self.render_calls += 1

    def refresh(self):
        self.refresh_calls += 1

    class _Root:
        def __init__(self, outer):
            self._outer = outer

        def after(self, delay_ms, callback):
            self._outer.rescheduled.append((delay_ms, callback))

    @property
    def root(self):
        return self._Root(self)


def test_refresh_complete_with_still_current_selection_updates_and_reschedules():
    widget = FakeRefresh(selected=["a", "b"])

    widget.refresh_complete(frozenset({"a", "b"}))

    assert widget.refresh_in_progress is False
    assert widget.last_updated is not None
    assert widget.render_calls == 1
    assert widget.refresh_calls == 0
    assert len(widget.rescheduled) == 1


def test_refresh_complete_with_stale_selection_kicks_an_immediate_refresh():
    widget = FakeRefresh(selected=["a"])  # selection changed after the refresh started

    widget.refresh_complete(frozenset({"a", "b"}))

    assert widget.refresh_in_progress is False
    assert widget.last_updated is None
    assert widget.render_calls == 0
    assert widget.refresh_calls == 1
    assert widget.rescheduled == []
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_refresh.py -v`
Expected: FAIL — `refresh_complete()` currently takes a single `prod_id` and compares it to `self.active_production` (which `FakeRefresh` doesn't define), raising `TypeError`/`AttributeError`.

- [ ] **Step 3: Update `refresh()`/`refresh_worker()`/`refresh_complete()`**

Replace:

```python
    def refresh(self):
        if self.refresh_in_progress:
            return
        prod_id = self.active_production
        self.refresh_in_progress = True
        self.render()  # show the "refreshing" button state right away, not
                       # whenever the next tick/ticker render happens to land
        threading.Thread(target=self.refresh_worker, args=(prod_id,), daemon=True).start()

    def refresh_worker(self, prod_id):
        try:
            # ALL_PRODUCTION_ID has no slot/manifest entry of its own — refresh
            # every real production's slot instead, each against its own
            # manifest's auto_resolve, so switching to the "All" tab keeps
            # every talent (not just the previously-active production's) live.
            if prod_id == ALL_PRODUCTION_ID:
                # Slots for every visible production always exist by now --
                # set_production_enabled() (main thread) creates one on the
                # spot whenever a production is turned back on, the same way
                # switch_production() does when the "All" tab is entered --
                # so this can read production_data directly without racing a
                # lazy _production_slot() create from this background thread.
                jobs = [(production["id"], self.production_data[production["id"]], production.get("auto_resolve"))
                        for production in self._visible_productions()]
            else:
                jobs = [(prod_id, self.production_data[prod_id], self._productions_by_id[prod_id].get("auto_resolve"))]
            tasks = [(job_prod_id, slot, auto_resolve, name, slug, target)
                     for job_prod_id, slot, auto_resolve in jobs
                     for name, slug, target, _ in slot["targets"]]
            if not tasks:
                return
            task_queue = queue.Queue()
            for task in tasks:
                task_queue.put(task)

            def drain_queue():
                while True:
                    try:
                        task = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    self.check_one(*task)

            # A small fixed-size pool draining a queue, not one thread per
            # talent: on the "All" tab across every production (hundreds of
            # talents for the VT variant) a thread-per-talent approach spawns
            # and tears down hundreds of OS threads every single refresh
            # cycle even though only 12 of them ever do real work at once.
            # Still plain daemon threads rather than ThreadPoolExecutor: its
            # worker threads register with concurrent.futures' own atexit
            # hook and get joined before the interpreter is allowed to exit,
            # so a single slow/hanging youtube.fetch_live_info() call — which
            # can stack multiple 20s-timeout network requests (channel-id
            # resolution, an internal retry on the browse call, and this
            # module's own 404 channel re-resolve path) well past a single
            # 20s bound — would keep the whole process — and the
            # single-instance mutex it holds — alive well after the window
            # closes. Daemon threads are simply abandoned on exit instead.
            pool_size = min(MAX_REFRESH_WORKERS, len(tasks))
            workers = [threading.Thread(target=drain_queue, daemon=True) for _ in range(pool_size)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        finally:
            try:
                self.root.after(0, self.refresh_complete, prod_id)
            except (RuntimeError, tk.TclError):
                # The window can be closed while a refresh is still in flight;
                # self.root is already destroyed at that point, nothing to update.
                pass

    def refresh_complete(self, prod_id):
        self.refresh_in_progress = False
        if self.tray is not None:
            self.tray.update_tooltip(self._tray_tooltip_text())
        if prod_id == self.active_production:
            self.last_updated = time.strftime("%H:%M:%S")
            self.render()
            self.root.after(REFRESH_INTERVAL_MS, self.refresh)
        else:
            # The user switched tabs while this (now-stale) production's
            # refresh was still in flight — kick an immediate refresh for
            # whatever's active now instead of waiting out this one's 60s
            # cycle. That refresh's own refresh_complete() schedules the
            # next periodic tick, so this doesn't create a second loop.
            self.refresh()
```

with:

```python
    def refresh(self):
        if self.refresh_in_progress:
            return
        # Captured before spawning the worker thread, so a selection change
        # mid-refresh can't mutate the set that thread is iterating.
        prod_ids = frozenset(self.selected_productions)
        self.refresh_in_progress = True
        self.render()  # show the "refreshing" button state right away, not
                       # whenever the next tick/ticker render happens to land
        threading.Thread(target=self.refresh_worker, args=(prod_ids,), daemon=True).start()

    def refresh_worker(self, prod_ids):
        try:
            # Every id in `prod_ids` already has a slot in production_data by
            # construction -- toggle_production_selection() (main thread)
            # always calls _production_slot() for a newly-selected id before
            # triggering this refresh, so this can read production_data
            # directly without racing a lazy _production_slot() create from
            # this background thread.
            jobs = [(prod_id, self.production_data[prod_id], self._productions_by_id[prod_id].get("auto_resolve"))
                    for prod_id in prod_ids]
            tasks = [(job_prod_id, slot, auto_resolve, name, slug, target)
                     for job_prod_id, slot, auto_resolve in jobs
                     for name, slug, target, _ in slot["targets"]]
            if not tasks:
                return
            task_queue = queue.Queue()
            for task in tasks:
                task_queue.put(task)

            def drain_queue():
                while True:
                    try:
                        task = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    self.check_one(*task)

            # A small fixed-size pool draining a queue, not one thread per
            # talent: selecting every production at once (hundreds of
            # talents for the VT variant) a thread-per-talent approach spawns
            # and tears down hundreds of OS threads every single refresh
            # cycle even though only 12 of them ever do real work at once.
            # Still plain daemon threads rather than ThreadPoolExecutor: its
            # worker threads register with concurrent.futures' own atexit
            # hook and get joined before the interpreter is allowed to exit,
            # so a single slow/hanging youtube.fetch_live_info() call — which
            # can stack multiple 20s-timeout network requests (channel-id
            # resolution, an internal retry on the browse call, and this
            # module's own 404 channel re-resolve path) well past a single
            # 20s bound — would keep the whole process — and the
            # single-instance mutex it holds — alive well after the window
            # closes. Daemon threads are simply abandoned on exit instead.
            pool_size = min(MAX_REFRESH_WORKERS, len(tasks))
            workers = [threading.Thread(target=drain_queue, daemon=True) for _ in range(pool_size)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        finally:
            try:
                self.root.after(0, self.refresh_complete, prod_ids)
            except (RuntimeError, tk.TclError):
                # The window can be closed while a refresh is still in flight;
                # self.root is already destroyed at that point, nothing to update.
                pass

    def refresh_complete(self, prod_ids):
        self.refresh_in_progress = False
        if self.tray is not None:
            self.tray.update_tooltip(self._tray_tooltip_text())
        if prod_ids == self.selected_productions:
            self.last_updated = time.strftime("%H:%M:%S")
            self.render()
            self.root.after(REFRESH_INTERVAL_MS, self.refresh)
        else:
            # The selection changed while this (now-stale) refresh was still
            # in flight — kick an immediate refresh for whatever's selected
            # now instead of waiting out this one's 60s cycle. That
            # refresh's own refresh_complete() schedules the next periodic
            # tick, so this doesn't create a second loop.
            self.refresh()
```

Remove the now-unused `ALL_PRODUCTION_ID` import at the top of `refresh.py`:

```python
from .talents import ALL_PRODUCTION_ID, UNOBSERVED_STATE
```

becomes:

```python
from .talents import UNOBSERVED_STATE
```

(Confirm with `grep -n "ALL_PRODUCTION_ID" deskwidget_core/refresh.py` — should show no matches after this edit.)

`check_one()`'s own comment a little further down also references the old name (purely
explanatory, no behavior change) — replace:

```python
    def check_one(self, prod_id, slot, auto_resolve, name, slug, target):
        # Operates on the explicit `slot` dict (self.production_data[prod_id])
        # rather than the self.targets/self.states/etc. properties, which
        # always reflect whichever production is active_production *right
        # now* — see the note above those properties.
```

with:

```python
    def check_one(self, prod_id, slot, auto_resolve, name, slug, target):
        # Operates on the explicit `slot` dict (self.production_data[prod_id])
        # rather than the self.targets/self.states/etc. properties, which
        # always reflect whichever productions are currently selected
        # *right now* — see the note above those properties.
```

`_resolve_channel_url()`'s own comment, a little further up, has the same stale
mention — replace:

```python
            # Guards against _merge_all_slots() reading/merging this dict on
            # the Tk main thread at the same time (see the note by "lock" in
            # _production_slot()).
```

with:

```python
            # Guards against _merge_slots() reading/merging this dict on
            # the Tk main thread at the same time (see the note by "lock" in
            # _production_slot()).
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_refresh.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Full-suite sanity check**

Run: `pytest -q`
Expected: PASS, no failures, no `active_production`/`switch_production`/`_all_targets`/`_merge_all_slots`/unused-`ALL_PRODUCTION_ID`-import errors anywhere in the collected modules.

- [ ] **Step 6: Commit**

```bash
git add deskwidget_core/refresh.py tests/test_refresh.py
git commit -m "refresh: refresh the selected production set instead of a single active id"
```

---

### Task 9: Manual verification (VT variant, live app)

**Files:** none (no code changes — this task exercises Tasks 1-8's combined result in the running app, since `widget.py`/`refresh.py`/`rendering.py`/`interaction.py` have no automated coverage in this repo).

- [ ] **Step 1: Launch the VT variant**

Use the `run` skill (or, if it reports no project-specific launch skill, `python -m variants.vt.profile` / however this repo's own dev-run convention starts VTDeskWidget — check `tools/`/`*.bat` first) with a fresh (or backed-up) `settings.json` so this starts from defaults.

- [ ] **Step 2: Verify plain multi-select toggling**

Click two different production tabs (not "All"). Confirm: both stay highlighted (accent fill), the talent grid shows both productions' talents grouped under a shaded band per production, and clicking either tab again deselects just that one (its talents disappear, its highlight clears, the other stays).

- [ ] **Step 3: Verify the never-empty guard**

With only one tab selected, click it again. Confirm nothing changes (it stays selected, highlighted, and on screen) — this is the "keep at least one" invariant, not a missed click.

- [ ] **Step 4: Verify the "All" shortcut**

With some but not all tabs selected, click "All". Confirm every real tab becomes highlighted and every production's talents appear (banded). Click "All" again. Confirm nothing changes (per the confirmed design: full-to-full is a no-op, not a deselect-all).

- [ ] **Step 5: Verify the enabled-productions cascade**

Open the productions checklist (top-right "productions" button) and disable a production that is currently selected (but not the only one selected). Confirm its tab disappears from the strip and its talents disappear from the grid, with the other selected production(s) unaffected. Then disable a production that is the *only* one currently selected. Confirm the selection falls back to every remaining visible production (all their tabs light up, all their talents appear banded) rather than leaving the view empty.

- [ ] **Step 6: Verify settings persistence across a restart**

Select a specific combination of two or three tabs, close the app, and relaunch it. Confirm the same combination is still selected. Inspect the saved `settings.json`: confirm it has a `"selected_productions"` list (not `"active_production"`).

- [ ] **Step 7: Verify the legacy migration path**

Hand-edit `settings.json` to remove `"selected_productions"` entirely and set `"active_production": "hololive"` (or whatever a real production id in this variant's manifest is). Relaunch. Confirm exactly that one production is selected on startup. Repeat with `"active_production": "__all__"`. Confirm every visible production is selected on startup.

- [ ] **Step 8: Verify keyboard activation**

Tab (keyboard) through the top controls into the production-tab strip and press Enter/Space on a tab. Confirm it toggles the same way a mouse click does.

- [ ] **Step 9: Verify the tray tooltip is unaffected by selection**

With only one production selected, hover the tray icon (or minimize to tray and hover there). Confirm the live/total counts in the tooltip still reflect *every enabled* production, not just the one currently selected — this is Task 2's explicit carve-out and is easy to silently regress.

No commit for this task (verification only). If any step surfaces a bug, fix it as a small follow-up commit referencing which task/step it corrects, then re-run the affected step.
