"""tkinter Toplevel popups: the theme-color palette, the font picker, the
productions checklist, and the right-click context menu. Each open_*()
follows the same overrideredirect-Toplevel-anchored-under-its-button pattern.
"""
import time
import tkinter as tk
import webbrowser

from . import appconfig, stream_log
from .config import FONT_UI_REGULAR, FONT_UI_SMALL, FONT_UI_SMALL_BOLD, FONT_UI_SMALL_UNDERLINE, FONT_UI_TINY
from .fonts import family_display_name, list_installed_fonts, set_font_family
from .talents import ALL_PRODUCTION_ID, production_display_name
from .theme import THEME_PALETTE

# Dark text color used on top of the accent color, both for a hovered
# top-level menu item (_menu_colors' activeforeground) and a selected font
# in the font picker's Listbox (selectforeground) -- named once so the two
# roles can't quietly drift apart.
_ACCENT_TEXT_COLOR = "#18181f"

HISTORY_LIST_MAX_EVENTS = 300
HISTORY_WINDOW_SIZE = "560x420"


class MenuMixin:
    def _position_popup_under_button(self, win, button_key):
        win.update_idletasks()
        rect = self.top_button_rects()[button_key]
        bx = self.root.winfo_x() + int(rect[0])
        by = self.root.winfo_y() + int(rect[3]) + 6
        win.geometry(f"+{bx}+{by}")

    def _menu_colors(self, colors):
        # Shared by show_context_menu()'s top-level menu and every submenu
        # it builds (lang/productions/font), so a future theme-color tweak
        # only has one place to change instead of drifting across each copy.
        return dict(
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=_ACCENT_TEXT_COLOR,
        )

    def _close_popup(self, attr_name, after_close=None):
        win = getattr(self, attr_name)
        if win is not None:
            setattr(self, attr_name, None)
            try:
                win.destroy()
            except tk.TclError:
                pass
            if after_close is not None:
                after_close()

    def _make_popup_toplevel(self, bg):
        # Shared shape for every anchored-under-its-button popup (palette,
        # font picker, productions checklist): borderless, always-on-top,
        # background set up front so each widget added below doesn't need
        # its own bg= boilerplate to match.
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=bg)
        return win

    def _toggle_popup(self, attr_name, open_fn):
        if getattr(self, attr_name) is not None:
            self._close_popup(attr_name)
            return
        open_fn()

    @staticmethod
    def _checked_label(label, checked):
        # Plain command labels with a "✓ " prefix when active, not
        # checkbuttons/radiobuttons -- a native checkmark glyph is barely
        # visible against this app's custom dark menu colors.
        return f"✓ {label}" if checked else label

    def toggle_palette(self):
        self._toggle_popup("palette_win", self.open_palette)

    def open_palette(self):
        colors = self.theme_colors()
        panel_hex = self._hex(colors["panel"][:3])
        muted_hex = self._hex(colors["muted"][:3])
        win = self._make_popup_toplevel(panel_hex)
        self.palette_win = win
        cols, swatch = 5, 40
        preview = tk.Label(win, text=self.t("palette_hint"), bg=panel_hex, fg=muted_hex,
                           font=FONT_UI_SMALL_BOLD, anchor="w")
        preview.grid(row=0, column=0, columnspan=cols, sticky="we", padx=6, pady=(6, 2))
        for i, (name, rgb) in enumerate(THEME_PALETTE):
            row, col = divmod(i, cols)
            cv = tk.Canvas(win, width=swatch, height=swatch, bg=panel_hex,
                          highlightthickness=0, cursor="hand2")
            if name == "Monochrome":
                # Drawn half-black/half-white so it reads as the neutral option
                # among all the hues, rather than just another flat swatch.
                cv.create_polygon(0, 0, swatch, 0, 0, swatch, fill="#000000", outline="")
                cv.create_polygon(swatch, 0, swatch, swatch, 0, swatch, fill="#ffffff", outline="")
            else:
                hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
                cv.create_rectangle(0, 0, swatch, swatch, fill=hex_color, outline="")
            cv.bind("<Button-1>", lambda event, idx=i: self.select_theme(idx))
            cv.bind("<Enter>", lambda event, n=name: preview.configure(text=n))
            cv.bind("<Leave>", lambda event: preview.configure(text=self.t("palette_hint")))
            cv.grid(row=row + 1, column=col, padx=2, pady=2)
        self._position_popup_under_button(win, "color")
        win.bind("<FocusOut>", lambda event: self.close_palette())
        win.focus_force()

    def close_palette(self):
        self._close_popup("palette_win")

    def select_theme(self, index):
        self.theme_index = index
        self.suppress_next_click = True
        self.close_palette()
        self.render()

    def toggle_font_menu(self):
        self._toggle_popup("font_win", self.open_font_menu)

    def open_font_menu(self):
        # Same overrideredirect-Toplevel-anchored-under-its-button pattern as
        # open_palette() above, but backed by a search box + scrollable
        # Listbox instead of a handful of fixed rows, since this lists every
        # font family installed on the PC (can easily be 200+).
        colors = self.theme_colors()
        panel_hex = self._hex(self.tint(colors["panel"][:3]))
        text_hex = self._hex(colors["text"])
        muted_hex = self._hex(colors["muted"])
        accent_hex = self._hex(self.accent_color()[:3])
        win = self._make_popup_toplevel(panel_hex)
        self.font_win = win

        all_families = [name for name, _files in list_installed_fonts()]
        # Populated by refresh_list() below with the (family, display_name)
        # pairs actually in the listbox -- click/key handlers need the
        # family identity (what's stored/compared as self.font_family),
        # not the localized text shown to the user, so listbox rows are
        # mapped back through this rather than reading the identity out of
        # the widget's own display text.
        current_matches = []

        hint = tk.Label(win, text=self.t("font_hint"), bg=panel_hex, fg=muted_hex,
                        font=FONT_UI_SMALL_BOLD, anchor="w")
        hint.grid(row=0, column=0, sticky="we", padx=8, pady=(6, 2))
        search_var = tk.StringVar()
        entry = tk.Entry(win, textvariable=search_var, bg=panel_hex, fg=text_hex,
                         insertbackground=text_hex, relief="flat",
                         highlightthickness=1, highlightbackground=muted_hex,
                         highlightcolor=accent_hex, font=FONT_UI_REGULAR)
        entry.grid(row=1, column=0, sticky="we", padx=8, pady=(0, 4))
        list_frame = tk.Frame(win, bg=panel_hex)
        list_frame.grid(row=2, column=0, padx=8, pady=(0, 8))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(
            list_frame, bg=panel_hex, fg=text_hex, selectbackground=accent_hex,
            selectforeground=_ACCENT_TEXT_COLOR, activestyle="none", highlightthickness=0,
            borderwidth=0, font=FONT_UI_REGULAR, width=30, height=10,
            yscrollcommand=scrollbar.set, exportselection=False,
        )
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        def refresh_list(*_args):
            query = search_var.get().casefold()
            pairs = [(name, family_display_name(name, self.lang)) for name in all_families]
            matches = ([pair for pair in pairs if query in pair[1].casefold()]
                       if query else pairs)
            current_matches[:] = matches
            listbox.delete(0, tk.END)
            for _name, display in matches:
                listbox.insert(tk.END, display)
            names = [name for name, _display in matches]
            if self.font_family in names:
                idx = names.index(self.font_family)
                listbox.selection_set(idx)
                listbox.see(idx)

        def commit(name):
            if name is not None:
                self.select_font_family(name)

        def commit_from_click(event):
            index = listbox.nearest(event.y)
            if 0 <= index < len(current_matches):
                commit(current_matches[index][0])

        def commit_from_key(event=None):
            selection = listbox.curselection()
            if selection:
                commit(current_matches[selection[0]][0])
            elif current_matches:
                commit(current_matches[0][0])

        def focus_out_check(win=win):
            # Deferred so a focus move BETWEEN this popup's own widgets
            # (entry -> listbox) isn't mistaken for the popup losing focus
            # entirely -- each widget's own FocusOut fires before the new
            # widget actually has focus, so focus_get() has to be read a
            # tick later once it has actually landed.
            if self.font_win is not win:
                return
            try:
                focused = win.focus_get()
            except tk.TclError:
                focused = None
            if focused is None or not str(focused).startswith(str(win)):
                self.close_font_menu()

        def on_focus_out(event=None):
            win.after(1, focus_out_check)

        search_var.trace_add("write", refresh_list)
        entry.bind("<Return>", commit_from_key)
        entry.bind("<Down>", lambda event: (listbox.focus_set(), listbox.selection_clear(0, tk.END),
                                            listbox.selection_set(0), "break"))
        entry.bind("<FocusOut>", on_focus_out)
        listbox.bind("<ButtonRelease-1>", commit_from_click)
        listbox.bind("<Return>", commit_from_key)
        listbox.bind("<FocusOut>", on_focus_out)

        refresh_list()
        self._position_popup_under_button(win, "font")
        entry.focus_force()

    def close_font_menu(self):
        self._close_popup("font_win")

    def select_font_family(self, name):
        self.font_family = name
        set_font_family(name)
        # _fit_label()/_label_width() cache by (label, size, bold) alone, not
        # by the actual font object, so a stale cached result for a
        # label/size pair already rendered before this switch would keep
        # returning the old family's font object even though font()'s own
        # cache was just cleared above.
        self._fit_label.cache_clear()
        self._label_width.cache_clear()
        self.close_font_menu()
        self.render()

    def toggle_productions_menu(self):
        self._toggle_popup("productions_win", self.open_productions_menu)

    def open_productions_menu(self):
        # Same overrideredirect-Toplevel-anchored-under-its-button pattern as
        # open_palette() above, but with one Checkbutton per production
        # (left checked/unchecked live, not committed via a separate OK
        # button) instead of a color grid.
        colors = self.theme_colors()
        panel_hex = self._hex(self.tint(colors["panel"][:3]))
        text_hex = self._hex(colors["text"])
        win = self._make_popup_toplevel(panel_hex)
        self.productions_win = win
        hint = tk.Label(win, text=self.t("productions_hint"), bg=panel_hex, fg=self._hex(colors["muted"]),
                        font=FONT_UI_SMALL_BOLD, anchor="w")
        hint.grid(row=0, column=0, sticky="we", padx=8, pady=(6, 2))
        self._production_menu_vars = []
        for i, production in enumerate(self.productions):
            prod_id = production["id"]
            var = tk.BooleanVar(value=prod_id in self.enabled_productions)
            self._production_menu_vars.append((prod_id, var))
            cb = tk.Checkbutton(
                win, text=production_display_name(production, self.lang), variable=var,
                command=lambda prod_id=prod_id, var=var: self._on_production_toggle(prod_id, var),
                bg=panel_hex, fg=text_hex, activebackground=panel_hex, activeforeground=text_hex,
                selectcolor=panel_hex, anchor="w", font=FONT_UI_REGULAR,
                highlightthickness=0, borderwidth=0,
            )
            cb.grid(row=i + 1, column=0, sticky="w", padx=8, pady=2)
        button_row = len(self.productions) + 1
        button_bar = tk.Frame(win, bg=panel_hex)
        button_bar.grid(row=button_row, column=0, sticky="we", padx=8, pady=(4, 6))
        enable_all_btn = tk.Label(
            button_bar, text=self.t("productions_enable_all"), bg=panel_hex, fg=text_hex,
            font=FONT_UI_SMALL_UNDERLINE, cursor="hand2",
        )
        enable_all_btn.pack(side="left")
        enable_all_btn.bind("<Button-1>", lambda event: self._set_all_productions_enabled(True))
        disable_all_btn = tk.Label(
            button_bar, text=self.t("productions_disable_all"), bg=panel_hex, fg=text_hex,
            font=FONT_UI_SMALL_UNDERLINE, cursor="hand2",
        )
        disable_all_btn.pack(side="left", padx=(12, 0))
        disable_all_btn.bind("<Button-1>", lambda event: self._set_all_productions_enabled(False))
        self._position_popup_under_button(win, "productions")
        win.bind("<FocusOut>", lambda event: self.close_productions_menu())
        win.focus_force()

    def close_productions_menu(self):
        # drop the button's "menu open" highlight
        self._close_popup("productions_win", after_close=self.render)

    def _on_production_toggle(self, prod_id, var):
        if not self.set_production_enabled(prod_id, var.get()):
            # Refusing to disable the last visible production -- snap the
            # checkbox back to checked instead of leaving no tabs at all.
            var.set(True)

    def _set_all_productions_enabled(self, enabled):
        # Same "keep at least one visible" guard as _on_production_toggle:
        # set_production_enabled() refuses to disable the last remaining one,
        # so disabling all naturally stops at one instead of leaving no tabs.
        for production in self.productions:
            self.set_production_enabled(production["id"], enabled)
        for prod_id, var in self._production_menu_vars:
            var.set(prod_id in self.enabled_productions)

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

    def show_context_menu(self, event):
        # Built fresh on each right-click (rather than a persistent Menu kept in
        # sync via traced Variables) so its colors/checkmarks/labels always match
        # whatever theme/language/state is current at click time.
        colors = self.theme_colors()
        menu = tk.Menu(
            self.root, tearoff=0,
            **self._menu_colors(colors),
            disabledforeground=self._hex(colors["muted"]),
            relief="flat", borderwidth=1,
        )
        _, row = self._hit_row(event.x, event.y)
        if row and row.get("copy_name"):
            menu.add_command(label=self.t("copy_name"),
                             command=lambda t=row["copy_name"]: self._copy_to_clipboard(t))
            if row.get("copy_title"):
                menu.add_command(label=self.t("copy_title"),
                                 command=lambda t=row["copy_title"]: self._copy_to_clipboard(t))
            menu.add_separator()
        # Plain commands with a "✓ " prefix on the label when active, not
        # checkbuttons — like dark_mode below, a Menu checkbutton's native
        # checkmark glyph is barely visible against this menu's custom dark
        # colors, so pin/live_only would otherwise look permanently unchecked.
        menu.add_command(label=self._checked_label(self.t("pin"), self.topmost),
                         command=self.toggle_topmost)
        menu.add_command(label=self._checked_label(self.t("fullscreen"), self.is_fullscreen),
                         command=self.toggle_fullscreen)
        menu.add_command(label=self._checked_label(self.t("live_filter"), self.live_only),
                         command=self.toggle_live_only)
        # Label names the CURRENT mode (like draw_mode_button()'s moon/sun icon),
        # not a fixed "Dark Mode" checkbox, for the same reason.
        menu.add_command(label=self.t("dark_mode") if self.dark_mode else self.t("light_mode"),
                         command=self.toggle_mode)
        menu.add_separator()
        lang_menu = tk.Menu(menu, tearoff=0, **self._menu_colors(colors))
        # Plain commands with a "✓ " prefix on the active language, not
        # radiobuttons — same invisible-indicator issue as pin/live_only above.
        lang_menu.add_command(label=self._checked_label(self.t("lang_ja"), self.lang == "ja"),
                              command=lambda: self.set_lang("ja"))
        lang_menu.add_command(label=self._checked_label(self.t("lang_en"), self.lang == "en"),
                              command=lambda: self.set_lang("en"))
        menu.add_cascade(label=self.t("language"), menu=lang_menu)
        # A single-production variant has nothing to filter (see
        # has_multiple_productions()/production_tabs()), so this cascade
        # (and the top-row productions button it mirrors) simply doesn't
        # exist for it rather than showing one permanently-checked,
        # can't-be-unchecked entry.
        if self.has_multiple_productions():
            productions_menu = tk.Menu(menu, tearoff=0, **self._menu_colors(colors))
            # Same enable/disable-all shortcut as open_productions_menu()'s
            # checklist popup, plus a "✓ " plain-command convention as
            # pin/live_only/lang above, one entry per production (mirrors that
            # popup's checkbox list) so the filter is reachable without the top
            # button.
            productions_menu.add_command(label=self.t("productions_enable_all"),
                                         command=lambda: self._set_all_productions_enabled(True))
            productions_menu.add_command(label=self.t("productions_disable_all"),
                                         command=lambda: self._set_all_productions_enabled(False))
            productions_menu.add_separator()
            for production in self.productions:
                prod_id = production["id"]
                label = production_display_name(production, self.lang)
                checked_label = self._checked_label(label, prod_id in self.enabled_productions)
                productions_menu.add_command(label=checked_label,
                                             command=lambda pid=prod_id: self.toggle_production(pid))
            menu.add_cascade(label=self.t("productions_button"), menu=productions_menu)
        menu.add_command(label=self.t("theme_color"), command=self.open_palette)
        font_menu = tk.Menu(menu, tearoff=0, **self._menu_colors(colors))
        # Same "✓ " plain-command convention as pin/live_only/lang/productions
        # above, one entry per Japanese-capable installed font (mirrors
        # open_font_menu()'s list) so the switch is reachable without the top
        # button.
        for name, _files in list_installed_fonts():
            display = family_display_name(name, self.lang)
            checked_label = self._checked_label(display, name == self.font_family)
            font_menu.add_command(label=checked_label,
                                  command=lambda n=name: self.select_font_family(n))
        menu.add_cascade(label=self.t("font_family"), menu=font_menu)
        menu.add_separator()
        menu.add_command(label=self.t("stream_history"), command=self.open_history_window)
        menu.add_command(label=self.t("tray_minimize"), command=self.minimize_to_tray)
        menu.add_separator()
        menu.add_command(label=self.t("refresh"), command=self.refresh)
        menu.add_command(label=self.t("close"), command=self.close)
        menu.add_separator()
        menu.add_command(label=f"{appconfig.app_name()} v{appconfig.version()}", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _history_today_summary(self, all_events):
        # "Today" stats are computed over the full (MAX_ENTRIES-capped) log,
        # not the HISTORY_LIST_MAX_EVENTS-newest slice used for the listbox
        # -- otherwise a busy day with more events than that across all
        # talents would silently drop older same-day entries from the count.
        today = time.strftime("%Y-%m-%d")
        today_starts = [event for event in all_events if event.get("event") == "start"
                        and time.strftime("%Y-%m-%d", time.localtime(event.get("ts", 0))) == today]
        # Keyed by (production_id, name), not name alone -- talent names are
        # only guaranteed unique within one production's own JSON file, and
        # a variant with several enabled productions (see
        # has_multiple_productions()) can otherwise merge two different
        # talents' counts together.
        counts = {}
        for event in today_starts:
            key = (event.get("production_id"), event.get("name", "?"))
            counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:5]
        summary = self.t("stream_history_today", count=len(today_starts))
        if top:
            summary += "  " + " / ".join(f"{name} x{count}" for (_, name), count in top)
        return summary

    def open_history_window(self):
        # A plain (OS-decorated) Toplevel rather than this file's usual
        # overrideredirect-popup pattern: this is a scrollable content window
        # the user may want to keep open and resize/move around, not a quick
        # anchored picker.
        if self.history_win is not None and self.history_win.winfo_exists():
            self.history_win.deiconify()
            self.history_win.lift()
            return
        colors = self.theme_colors()
        panel_hex = self._hex(self.tint(colors["panel"][:3]))
        text_hex = self._hex(colors["text"])
        muted_hex = self._hex(colors["muted"])

        win = tk.Toplevel(self.root)
        self.history_win = win
        win.title(self.t("stream_history"))
        win.geometry(HISTORY_WINDOW_SIZE)
        win.configure(bg=panel_hex)

        all_events = stream_log.load_events()
        events = all_events[:HISTORY_LIST_MAX_EVENTS]
        summary = self._history_today_summary(all_events)

        tk.Label(win, text=summary, bg=panel_hex, fg=text_hex, anchor="w", justify="left",
                wraplength=540, font=FONT_UI_SMALL_BOLD).pack(fill="x", padx=10, pady=(10, 4))

        list_frame = tk.Frame(win, bg=panel_hex)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(
            list_frame, bg=panel_hex, fg=text_hex, activestyle="none",
            highlightthickness=0, borderwidth=0, font=FONT_UI_SMALL,
            yscrollcommand=scrollbar.set,
        )
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        multi = self.has_multiple_productions()
        event_urls = []
        for event in events:
            timestamp = time.strftime("%m/%d %H:%M:%S", time.localtime(event.get("ts", 0)))
            production = self._productions_by_id.get(event.get("production_id"))
            prod_prefix = f"[{production_display_name(production, self.lang)}] " if multi and production else ""
            name = event.get("name", "?")
            url = None
            if event.get("event") == "start":
                title = event.get("title")
                suffix = f" - {title}" if title else ""
                url = event.get("url")
                url_suffix = f"  {url}" if url else ""
                line = f"{timestamp}  {prod_prefix}{name}  ● {self.t('stream_start')}{suffix}{url_suffix}"
            else:
                line = f"{timestamp}  {prod_prefix}{name}  ○ {self.t('stream_end')}"
            listbox.insert(tk.END, line)
            event_urls.append(url)
        if not events:
            listbox.insert(tk.END, self.t("stream_history_empty"))

        def open_selected_url(_event):
            index = listbox.nearest(_event.y)
            if 0 <= index < len(event_urls) and event_urls[index]:
                webbrowser.open(event_urls[index], new=2)

        listbox.bind("<Double-Button-1>", open_selected_url)

        tk.Label(win, text=self.t("stream_history_hint"), bg=panel_hex, fg=muted_hex,
                font=FONT_UI_TINY).pack(anchor="w", padx=10, pady=(0, 4))

        close_btn = tk.Label(win, text=self.t("close"), bg=panel_hex, fg=muted_hex,
                             font=FONT_UI_SMALL_UNDERLINE, cursor="hand2")
        close_btn.pack(anchor="e", padx=10, pady=(0, 10))
        close_btn.bind("<Button-1>", lambda event: self._close_popup("history_win"))
