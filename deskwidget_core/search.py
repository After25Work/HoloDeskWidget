"""Incremental stream-title filter: the always-visible search box in the
control row, and the single predicate every "is this row visible" decision in
the app funnels through.

The text field itself is a real tk.Entry placed on top of the rendered image
rather than a hand-rolled key handler drawing into the PIL panel like the
rest of this UI does. A custom field would have to reimplement Windows IME
composition to let anyone type a Japanese title at all -- the exact thing
this filter is most often used for -- so the one native widget in the panel
buys correct kana/kanji input, selection, and clipboard behavior for free.
Everything around it (the box it sits in, the magnifier, the clear button,
the hint) is still drawn by rendering.py so the row reads as part of the
panel.
"""
import tkinter as tk
from typing import Optional

from .config import FONT_UI_REGULAR


class SearchMixin:
    def init_search(self):
        # self.title_query is the raw text (what the entry shows and what
        # menus.py tests for "is a filter active"); the casefolded copy is
        # what row_matches_title() compares against, precomputed here rather
        # than per row per render -- compute_grid() consults it for every
        # talent on every ~60ms ticker tick.
        self.title_query = ""
        self._title_query_folded = ""
        self.search_entry: Optional[tk.Entry] = None
        # Last geometry actually applied to the entry, so sync_search_entry()
        # can skip a place_configure() on the (overwhelmingly common) render
        # where nothing about the window has moved -- see its own note.
        self._search_entry_geometry = None
        self._search_entry_colors = None

    @property
    def show_titles(self):
        # "One full-width row per talent, with the now-playing ticker beside
        # the name" -- the live-only view's presentation, which a title
        # filter needs too: filtering on a title you can't see would be
        # guesswork. Every place that used to branch on self.live_only for
        # *presentation* (rather than for the state != "live" filter itself)
        # reads this instead.
        return self.live_only or bool(self._title_query_folded)

    def row_matches_title(self, title):
        if not self._title_query_folded:
            return True
        # A talent with no live title (offline, or live with an empty title)
        # can never match a non-empty query -- so a query implicitly narrows
        # the list to live rows, which is what makes the filtered view
        # equivalent to the live-only one.
        return bool(title) and self._title_query_folded in title.casefold()

    def row_visible(self, name, state, titles):
        # The single "does this talent get a row" test, shared by
        # build_grid_layout() (what's laid out), _visible_talent_labels()
        # (what the shared label size is measured against) and the status
        # bar's own match count, so those three can never disagree about
        # which rows the current filters leave on screen.
        if self.live_only and state != "live":
            return False
        return self.row_matches_title(titles.get(name))

    def set_title_query(self, text):
        text = text.strip()
        if text == self.title_query:
            return
        self.title_query = text
        self._title_query_folded = text.casefold()
        # Nothing is refit or resized here on purpose: a filter that
        # rewrote the window height (the way toggle_live_only() does) would
        # make the panel jump on every keystroke. The grid keeps its
        # current window and simply re-lays out inside it -- and
        # compute_grid() pins its growth ceiling to 1.0 while a query is
        # active, so narrowing from many matches to one doesn't balloon the
        # remaining row's text either.
        self.focus_index = None
        self.request_render()

    def clear_title_query(self):
        # Both halves, unconditionally. Emptying the widget fires its own
        # trace, which calls set_title_query("") -- but only if the widget
        # actually held text, and only if it exists at all (the context menu's
        # "clear filter" entry and the panel's × button both reach this, and
        # neither is guaranteed to run after a keystroke). set_title_query()
        # early-returns when the text is already what it is being set to, so
        # the normal path still costs exactly one render; the call below is
        # what keeps the state from being stranded when the entry had nothing
        # to delete.
        if self.search_entry is not None:
            self.search_entry.delete(0, tk.END)
        self.set_title_query("")

    def focus_search(self, event=None):
        if self.search_entry is not None:
            self.search_entry.focus_set()
            self.search_entry.select_range(0, tk.END)
            self.search_entry.icursor(tk.END)
        return "break"

    def _create_search_entry(self):
        # Created only once the render surface exists, and therefore after
        # it: Tk stacks siblings in creation order, so an entry built before
        # the surface Label would be painted underneath the panel image and
        # never be visible or clickable.
        var = tk.StringVar()
        entry = tk.Entry(self.root, textvariable=var, relief="flat", borderwidth=0,
                         highlightthickness=0, font=FONT_UI_REGULAR)
        var.trace_add("write", lambda *_args: self.set_title_query(var.get()))
        entry.bind("<Escape>", self._on_search_escape)
        entry.bind("<Return>", lambda event: "break")
        self.search_entry = entry
        self._search_query_var = var
        return entry

    def _on_search_escape(self, event=None):
        # Escape in the field clears it and hands focus back to the panel, so
        # the surface's own Escape binding (drop the keyboard focus ring) and
        # every other key binding are live again without a mouse click.
        self.clear_title_query()
        self.surface.focus_set()
        return "break"

    def sync_search_entry(self):
        # Called at the end of every render() -- including the ~60ms ticker
        # ticks -- so both the guards below matter: place_configure() and
        # configure() each force a redraw of the widget, and reapplying an
        # unchanged geometry/color on every tick made the field flicker
        # while a now-playing ticker was scrolling next to it.
        if self.surface is None:
            return
        if self.search_entry is None:
            self._create_search_entry()
        left, top, right, bottom = self.search_entry_rect()
        geometry = (round(left), round(top), round(right - left), round(bottom - top))
        if geometry != self._search_entry_geometry:
            self._search_entry_geometry = geometry
            x, y, width, height = geometry
            self.search_entry.place(x=x, y=y, width=width, height=height)
        colors = self.theme_colors()
        # Matches the drawn box behind it (see rendering.py's
        # _draw_search_row), which uses this same status_bg tint, so the
        # native widget doesn't read as a rectangle pasted onto the panel.
        background = self._hex(self.background_color(colors["status_bg"]))
        foreground = self._hex(colors["text"])
        entry_colors = (background, foreground)
        if entry_colors != self._search_entry_colors:
            self._search_entry_colors = entry_colors
            self.search_entry.configure(bg=background, fg=foreground,
                                        insertbackground=foreground,
                                        selectbackground=self._hex(self.accent_color()[:3]),
                                        selectforeground=background)
