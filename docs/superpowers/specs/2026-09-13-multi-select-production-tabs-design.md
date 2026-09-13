# Multi-select production tabs — design

## Goal

The top tab strip that switches between productions (`GridMixin.production_tabs()`,
rendered by `RenderingMixin._draw_tabs()`) currently lets the user view exactly one
production at a time — a real production, or the pseudo "All" tab that merges every
enabled production together. This changes that strip from single-select to
multi-select: any combination of the enabled productions can be selected at once, and
the view merges exactly that combination (using the merge logic the "All" tab already
has, generalized to an arbitrary subset).

This only affects variants with more than one production loaded
(`has_multiple_productions()`); a single-production variant draws no tab strip today
and continues to draw none.

Out of scope: the separate "which productions show as a tab at all" checklist
(`enabled_productions`, `open_productions_menu()`/the right-click productions submenu)
is untouched — this design only changes which of the *shown* tabs are currently
selected for viewing.

## Data model

`widget.py`'s `self.active_production` (a single production id, or
`ALL_PRODUCTION_ID`) is replaced by `self.selected_productions`: a `set` of real
production ids (never containing `ALL_PRODUCTION_ID` — that pseudo-id stays a
click target/shortcut, never a member of the selection).

Invariant: `self.selected_productions` is never empty while the widget is running.
Every path that would remove an id from it (a tab click, or a production being
disabled via the enabled-productions checklist) must refuse the removal if it would
leave the set empty, exactly like `enabled_productions`' own existing "keep at least
one visible" guard in `set_production_enabled()`.

## Selection behavior

`switch_production(prod_id)` is replaced by `toggle_production_selection(prod_id)`:

- **Real production id**: toggle membership in `self.selected_productions`.
  Adding is always allowed. Removing is refused (no-op) if this id is the only
  member of the set.
- **`ALL_PRODUCTION_ID`** (the "All" tab): if `self.selected_productions` does not
  already equal the full set of currently-visible production ids
  (`{p["id"] for p in self._visible_productions()}`), set it to that full set
  ("select all"). If it already equals that full set, do nothing — clicking "All"
  again while everything is selected has no effect (confirmed with the user: this
  is a deliberate consequence of the "never empty" invariant, not a bug).

Both branches, after changing the set, do the same follow-up work
`switch_production()` does today: ensure a `_production_slot()` exists for every
newly-selected id, reset `focus_index`, `fit_height()` if `live_only`,
`request_render()`, `refresh()`.

```python
def toggle_production_selection(self, prod_id):
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

## Merged data properties

`targets`/`states`/`channel_urls`/`live_urls`/`live_titles` currently branch on
`self.active_production == ALL_PRODUCTION_ID` to decide between one production's
slot and a full merge (`_all_targets()`/`_merge_all_slots()`). That branch goes away;
merging always runs, scoped to whichever *visible* productions are currently
*selected*:

```python
def _selected_productions_list(self):
    return [p for p in self._visible_productions() if p["id"] in self.selected_productions]
```

`_aggregate_keys()` and `_merge_all_slots()` both currently hardcode
`self._visible_productions()` as the list they aggregate/merge over. There are two
different callers that need two different lists now: the `states`/`channel_urls`/
`live_urls`/`live_titles` properties need the *selected* subset, but
`_tray_tooltip_text()`'s own `self._merge_all_slots("states")` call needs to keep
summarizing *every visible* production regardless of what's selected (the tray
tooltip is a global "how much is live across everything enabled" glance, not tied to
whatever tab happens to be showing — that's already true today, since it currently
runs unconditionally, not behind an `active_production == ALL_PRODUCTION_ID` check).
So both helpers take an explicit `productions` list instead of reading
`_visible_productions()` internally:

```python
def _aggregate_keys(self, productions):
    ...  # same body as today, `for production in productions:` instead of
         # `for production in self._visible_productions():`

def _merge_slots(self, productions, key):  # renamed from _merge_all_slots
    aggregate_keys = self._aggregate_keys(productions)
    ...  # same body as today, `for production in productions:` instead of
         # `for production in self._visible_productions():`
```

`_slot_field(key)` (backing the four dict properties) calls
`self._merge_slots(self._selected_productions_list(), key)`.
`_tray_tooltip_text()` calls `self._merge_slots(self._visible_productions(), "states")`
— same list it already effectively used, just passed explicitly now instead of the
helper reaching for it internally. This part behaves identically at exactly one
selected production (the aggregate key for the first, only production that ever uses
a given name is always the plain name — see `_aggregate_keys()`'s `count == 0`
branch — so a one-production merge produces exactly the same dict
`_production_slot(prod_id)[key]` already holds), so the properties can always go
through `_merge_slots()` with no special-case for one selection.

`_all_targets()` is different and needs a real fork, not just a rename: it
unconditionally retags every talent's `unit` field to its *production's own display
name* (see the comment at grid_layout.py:526-536 on the "All" tab's shaded
per-production bands) — appropriate when merging several productions together, but
wrong for exactly one selected production, which should keep showing that
production's own internal sub-grouping (e.g. "JP"/"ID"/"EN") exactly as the current
single-tab fast path (`_production_slot(prod_id)["targets"]`, no retagging) does
today. The replacement, `_selected_targets()`:

```python
def _selected_targets(self):
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

`grid_layout.py`'s per-production shaded-band drawing
(`build_grid_layout()`/`compute_grid()`, currently gated on
`self.active_production == ALL_PRODUCTION_ID`) is gated on
`len(self._selected_productions_list()) > 1` instead — true exactly when
`_selected_targets()` took the retagging branch above, so the bands still appear
exactly when rows are grouped by production rather than by each production's own
sub-units. `_selected_productions_list()` is called directly (duck-typed, like every
other `self.<widget-method>()` call already in `grid_layout.py`) rather than
re-deriving the count from `self.selected_productions` alone, since only the
visible-and-selected count matters for what `_selected_targets()` actually rendered.

## Rendering

`RenderingMixin._draw_tabs()`'s `active` check changes per tab:

- Real production tab: `tab["id"] in self.selected_productions`.
- "All" tab: `set(p["id"] for p in self._visible_productions()) == self.selected_productions`.

Visually this means any number of tabs can show the accent-filled "selected" state
at once, and "All" lights up exactly when that amounts to everything.

## Refresh machinery (`refresh.py`)

`refresh()`/`refresh_worker()`/`refresh_complete()` currently key everything off a
single `prod_id` (`self.active_production`), special-casing `ALL_PRODUCTION_ID` into
"every visible production". This collapses into one path:

- `refresh()` captures `prod_ids = frozenset(self.selected_productions)` on the main
  thread (before spawning the worker thread, so a selection change mid-refresh can't
  mutate the set the worker is iterating) and passes it to `refresh_worker(prod_ids)`
  and, via its `finally`, to `refresh_complete(prod_ids)`.
- `refresh_worker(prod_ids)` drops the `ALL_PRODUCTION_ID` branch entirely and builds
  its job list directly from `prod_ids`: `[(pid, self.production_data[pid],
  self._productions_by_id[pid].get("auto_resolve")) for pid in prod_ids]`. Every
  `pid` in a snapshot taken from `self.selected_productions` already has a slot in
  `self.production_data` by construction — `toggle_production_selection()` always
  calls `_production_slot()` for a newly-added id (on the main thread) before
  triggering this refresh — so this doesn't need `_visible_productions()`'s extra
  lookup/filter the old `ALL_PRODUCTION_ID` branch did.
- `refresh_complete(prod_ids)` compares the snapshot it was given against the
  *current* `self.selected_productions`: equal means "still current" (update
  `last_updated`, render, schedule the next periodic refresh); not equal means the
  selection changed while this refresh was in flight, so it kicks an immediate
  `self.refresh()` for the new selection instead (same staleness handling as today,
  generalized from `==` on a single id to `==` on a set).

## Cascading from the enabled-productions checklist

`menus.py`'s `set_production_enabled(prod_id, enabled)` already refuses to disable
the last visible production. When it disables one that *is* currently selected, it
must also drop it from `self.selected_productions`. If that empties the selection
(the disabled production was the only one selected), fall back to selecting every
remaining visible production — the same "fall back to the merged view" behavior
`switch_production(ALL_PRODUCTION_ID)` provides today when the active production is
disabled:

```python
def set_production_enabled(self, prod_id, enabled):
    if enabled:
        self.enabled_productions.add(prod_id)
        # No slot pre-creation needed here any more: a newly re-enabled
        # production starts deselected (see toggle_production_selection),
        # so its slot is created lazily whenever it's actually selected.
    else:
        if len(self.enabled_productions) <= 1:
            return False
        self.enabled_productions.discard(prod_id)
        if prod_id in self.selected_productions:
            self.selected_productions.discard(prod_id)
            if not self.selected_productions:
                self.selected_productions = {p["id"] for p in self._visible_productions()}
                for production in self._visible_productions():
                    self._production_slot(production["id"])
    self.render()
    return True
```

Note the behavior change this implies: today, re-enabling a previously-disabled
production doesn't change what's on screen until the user clicks its tab. That stays
true here too — enabling only makes a tab reappear in the strip, it never adds that
production to the current selection.

## Interaction / keyboard wiring

- `interaction.py`'s `click()`: the tab-hit branch calls
  `self.toggle_production_selection(hit_tab["id"])` instead of `switch_production`.
- `grid_layout.py`'s `focusable_items()`: each tab's `"activate"` lambda calls
  `toggle_production_selection` instead of `switch_production`. No change to hit-rect
  geometry, tab count, or keyboard tab order — only which method a tab invokes.

## Settings persistence (`config.py`)

`DEFAULT_SETTINGS["active_production"]` is replaced by
`DEFAULT_SETTINGS["selected_productions"]: []` (empty list = "no preference saved",
mirroring the existing `enabled_productions` convention). `load_settings()` coerces
it the same way `enabled_productions` is coerced (drop non-string entries, fall back
to `[]` if the raw value isn't a list).

`widget.py._load_settings()` resolves the final set:

1. Filter the saved list down to ids that exist in the currently-loaded manifest.
2. If that leaves at least one id, use it.
3. Otherwise, fall back once to the legacy single-value key if present: a
   `settings.json` written before this change has `"active_production"` but no
   `"selected_productions"`. If `active_production == ALL_PRODUCTION_ID`, seed the
   selection with every visible production; if it's a valid real production id, seed
   with just that one.
4. Otherwise (fresh install, or nothing valid survives either path), default to
   `{self.productions[0]["id"]}`.

`current_settings()` writes `"selected_productions"` (sorted list, for deterministic
diffs) and stops writing `"active_production"` — the legacy key is read-only
migration input, never written back.

## Testing

- `tests/test_config.py`: coercion of the new `selected_productions` list setting
  (mirrors existing `enabled_productions` tests).
- `tests/test_grid_layout.py` / `tests/test_grid_columns.py`: tab click/keyboard
  activation now toggles membership rather than replacing a single active id;
  multi-selected merge output; the "All" tab's select-all/no-op behavior; the
  never-empty guard on both the last-selected-tab click and the disable-last-selected
  cascade from the enabled-productions checklist.
- `tests/test_talents.py`: unaffected (no changes to `ALL_PRODUCTION_ID`/
  `ALL_PRODUCTION`'s own definitions).
- `tests/test_grid_columns.py`: `FakeGrid.__init__` sets `self.active_production =
  "test"` purely so `build_grid_layout()`'s band-drawing condition has something to
  read — replace with a trivial `_selected_productions_list(self): return
  [{"id": "test"}]` method (one entry, so the band condition still evaluates to
  "not banded", matching today's behavior for this stub).

## Non-goals

- No new UI for multi-selecting from the right-click context menu's productions
  submenu — that submenu keeps controlling only `enabled_productions` (show/hide a
  tab), not selection.
- No modifier-key (ctrl/shift) click behavior — every tab is a plain-click toggle.
