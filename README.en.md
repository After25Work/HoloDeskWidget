# HoloDeskWidget / VTDeskWidget

English | [日本語](README.md)

A monorepo that builds two Windows desktop widgets -- each keeping VTuber talents' live-stream status visible at all times -- as two separate exes from one shared engine (`deskwidget_core/`).

| Variant | Directory | What it shows |
|---|---|---|
| **HoloDeskWidget** | [`variants/holo/`](variants/holo/README.en.md) | Single-production: hololive talents only |
| **VTDeskWidget** | [`variants/vt/`](variants/vt/README.en.md) | Multiple productions (hololive, NIJISANJI, Aogiri Highschool, and more), switchable by tab |

For features, screenshots, setup, and release instructions, see each variant's own README (linked above). This file only describes the overall repository layout.

## Structure

- `deskwidget_core/` — the engine package shared by both apps. A variant with only one production (Holo) never shows the multi-production tab-switching UI (tab strip, productions picker button) at all -- it's driven entirely by how many productions that variant's data ships.
- `variants/holo/` / `variants/vt/` — each app's own data (talent-list JSON, version, and a `profile.py` with its accent color etc.) and end-user documentation.
- `start_widget_holo.py` / `start_widget_vt.py` — each app's launch entry point. `start_widget_holo.bat` / `start_widget_vt.bat` launch them from a development environment.
- `build_widget.bat holo|vt` / `release_widget.bat holo|vt` — build/release scripts (take the variant name as an argument). See `.claude/skills/release/SKILL.md` for details.
- `tools/` — developer tooling (currently just the Holo-variant screenshot-capture script).

The two apps are versioned and released independently (`variants/holo/version.py` / `variants/vt/version.py`).

## License

[MIT License](LICENSE). This license covers the source code only; it does not grant any rights to the trademarks or names of the talents/productions this app references.
