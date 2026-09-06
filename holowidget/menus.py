"""tkinter Toplevel popups: the theme-color palette, the font picker, and the
right-click context menu. Each open_*() follows the same
overrideredirect-Toplevel-anchored-under-its-button pattern.
"""
import tkinter as tk

from .fonts import family_display_name, list_installed_fonts, set_font_family
from .theme import THEME_PALETTE
from .version import __version__


class MenuMixin:
    def _position_popup_under_button(self, win, button_key):
        win.update_idletasks()
        rect = self.top_button_rects()[button_key]
        bx = self.root.winfo_x() + int(rect[0])
        by = self.root.winfo_y() + int(rect[3]) + 6
        win.geometry(f"+{bx}+{by}")

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

    def toggle_palette(self):
        if self.palette_win is not None:
            self.close_palette()
            return
        self.open_palette()

    def open_palette(self):
        colors = self.theme_colors()
        panel_hex = self._hex(colors["panel"][:3])
        muted_hex = self._hex(colors["muted"][:3])
        win = tk.Toplevel(self.root)
        self.palette_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=panel_hex)
        cols, swatch = 5, 40
        preview = tk.Label(win, text=self.t("palette_hint"), bg=panel_hex, fg=muted_hex,
                           font=("Yu Gothic UI", 9, "bold"), anchor="w")
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
        if self.font_win is not None:
            self.close_font_menu()
            return
        self.open_font_menu()

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
        win = tk.Toplevel(self.root)
        self.font_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=panel_hex)

        all_families = [name for name, _files in list_installed_fonts()]
        # Populated by refresh_list() below with the (family, display_name)
        # pairs actually in the listbox -- click/key handlers need the
        # family identity (what's stored/compared as self.font_family), not
        # the localized text shown to the user, so listbox rows are mapped
        # back through this rather than reading the identity out of the
        # widget's own display text.
        current_matches = []

        hint = tk.Label(win, text=self.t("font_hint"), bg=panel_hex, fg=muted_hex,
                        font=("Yu Gothic UI", 9, "bold"), anchor="w")
        hint.grid(row=0, column=0, sticky="we", padx=8, pady=(6, 2))
        search_var = tk.StringVar()
        entry = tk.Entry(win, textvariable=search_var, bg=panel_hex, fg=text_hex,
                         insertbackground=text_hex, relief="flat",
                         highlightthickness=1, highlightbackground=muted_hex,
                         highlightcolor=accent_hex, font=("Yu Gothic UI", 10))
        entry.grid(row=1, column=0, sticky="we", padx=8, pady=(0, 4))
        list_frame = tk.Frame(win, bg=panel_hex)
        list_frame.grid(row=2, column=0, padx=8, pady=(0, 8))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(
            list_frame, bg=panel_hex, fg=text_hex, selectbackground=accent_hex,
            selectforeground="#1a1a1f", activestyle="none", highlightthickness=0,
            borderwidth=0, font=("Yu Gothic UI", 10), width=30, height=10,
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
        # _fit_label() caches by (label, size, bold) alone, not by the actual
        # font object, so a stale cached result for a label/size pair
        # already rendered before this switch would keep returning the old
        # family's font object even though font()'s own cache was just
        # cleared above.
        self._fit_label.cache_clear()
        self.close_font_menu()
        self.render()

    def show_context_menu(self, event):
        # Built fresh on each right-click (rather than a persistent Menu kept in
        # sync via traced Variables) so its colors/checkmarks/labels always match
        # whatever theme/language/state is current at click time.
        colors = self.theme_colors()
        menu = tk.Menu(
            self.root, tearoff=0,
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=self._hex((24, 24, 31)),
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
        pin_label = f"✓ {self.t('pin')}" if self.topmost else self.t("pin")
        menu.add_command(label=pin_label, command=self.toggle_topmost)
        fullscreen_label = f"✓ {self.t('fullscreen')}" if self.is_fullscreen else self.t("fullscreen")
        menu.add_command(label=fullscreen_label, command=self.toggle_fullscreen)
        live_label = f"✓ {self.t('live_filter')}" if self.live_only else self.t("live_filter")
        menu.add_command(label=live_label, command=self.toggle_live_only)
        # Label names the CURRENT mode (like draw_mode_button()'s moon/sun icon),
        # not a fixed "Dark Mode" checkbox, for the same reason.
        menu.add_command(label=self.t("dark_mode") if self.dark_mode else self.t("light_mode"),
                         command=self.toggle_mode)
        menu.add_separator()
        lang_menu = tk.Menu(
            menu, tearoff=0,
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=self._hex((24, 24, 31)),
        )
        # Plain commands with a "✓ " prefix on the active language, not
        # radiobuttons — same invisible-indicator issue as pin/live_only above.
        ja_label = f"✓ {self.t('lang_ja')}" if self.lang == "ja" else self.t("lang_ja")
        lang_menu.add_command(label=ja_label, command=lambda: self.set_lang("ja"))
        en_label = f"✓ {self.t('lang_en')}" if self.lang == "en" else self.t("lang_en")
        lang_menu.add_command(label=en_label, command=lambda: self.set_lang("en"))
        menu.add_cascade(label=self.t("language"), menu=lang_menu)
        menu.add_command(label=self.t("theme_color"), command=self.open_palette)
        font_menu = tk.Menu(
            menu, tearoff=0,
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=self._hex((24, 24, 31)),
        )
        # Same "✓ " plain-command convention as pin/live_only/lang above, one
        # entry per Japanese-capable installed font (mirrors open_font_menu()'s
        # list) so the switch is reachable without the top button.
        for name, _files in list_installed_fonts():
            display = family_display_name(name, self.lang)
            checked_label = f"✓ {display}" if name == self.font_family else display
            font_menu.add_command(label=checked_label,
                                  command=lambda n=name: self.select_font_family(n))
        menu.add_cascade(label=self.t("font_family"), menu=font_menu)
        menu.add_separator()
        menu.add_command(label=self.t("refresh"), command=self.refresh)
        menu.add_command(label=self.t("close"), command=self.close)
        menu.add_separator()
        menu.add_command(label=f"HoloDeskWidget v{__version__}", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
