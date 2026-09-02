# HoloDeskWidget

English | [日本語](README.md)

A Windows desktop widget that keeps the live-stream status of hololive talents visible at all times.

## Structure

- `start_widget_native.py` — launch entry point (checks for duplicate instances → runs the `holowidget` widget's mainloop)
- `holowidget/` — main package (Win32 layered-window implementation supporting always-on-top, transparency, and drag-to-move)
  - `widget.py` — the window itself (drawing and event handling)
  - `config.py` — window defaults and `settings.json` read/write
  - `talents.py` — loads `talents.json`
  - `youtube.py` — channel resolution and live-status scraping
  - `theme.py` / `strings.py` / `fonts.py` — colors, localized strings, and fonts
  - `layout.py` — layout table for the top-right button row
  - `paths.py` — path resolution and logging (size-capped rotation)
  - `single_instance.py` — prevents duplicate instances (Win32 mutex)
  - `version.py` — version number (shown in the right-click menu)
- `talents.json` — list of talents to display (name, unit, slug, known channel URL)
- `start_widget.bat` — launcher for the native version
- `build_widget.bat` — builds `dist/HoloDesk Widget.exe` with PyInstaller
- `find_python.bat` — shared Python-detection script used by `start_widget.bat`/`build_widget.bat`
- `release_widget.bat` — builds and packages the distributable zip (`release/HoloDeskWidget-v<version>.zip`)
- `docs/Readme.html` / `docs/Readme.en.html` — end-user usage guides (bundled into the release zip)

## Setup

Requires Python 3.10+ and the following dependencies.

```bash
pip install -r requirements.txt
```

## Launching

### From the development environment

```bash
start_widget.bat
```

`start_widget.bat` auto-detects the Python installation, checks that `pythonw.exe` exists, verifies Pillow is installed, and then launches the widget. If an error occurs, check `start_widget.log`.

### From the distributed release zip

Extract `release/HoloDeskWidget-v<version>.zip` and double-click `HoloDesk Widget.exe` to launch it. No Python installation or other setup is required. If Windows SmartScreen shows a warning on first launch, choose "More info" → "Run anyway" (this is expected for an unsigned executable).

## Version

Current version: **1.0.0**

`__version__` in `holowidget/version.py` is the single source of truth (it is also shown in the widget's right-click menu). Update this value manually when releasing. `release_widget.bat` reads this value, builds the exe via `build_widget.bat` (PyInstaller), and packages the exe, `talents.json`, and `docs/Readme*.html` into `release/HoloDeskWidget-v<version>.zip`.

## Release process

1. To bump the version, update `__version__` in `holowidget/version.py`, along with the matching `Current version: **x.y.z**` string in this file, the `現在のバージョン: **x.y.z**` string in `README.md`, and the version strings embedded in `docs/Readme.html` / `docs/Readme.en.html`. To update all five locations at once, use:
   ```bash
   python .claude/skills/release/scripts/bump_version.py <old_version> <new_version>
   ```
2. Run `release_widget.bat`. It calls `build_widget.bat` (PyInstaller, must be installed) to build `dist/HoloDesk Widget.exe`, then packages the exe, `talents.json`, `docs/Readme.html`, and `docs/Readme.en.html` into `release/HoloDeskWidget-v<version>.zip` (runtime-generated files like `settings.json` and logs are excluded).
3. Distribute the resulting `release/HoloDeskWidget-v<version>.zip`. `build/`, `dist/`, and `release/` are all gitignored.

## Updating the talent list

Add or edit entries in `talents.json` using the format `{"name": "...", "unit": "...", "slug": "...", "channel_url": "..."}`. Specify `channel_url` only when the channel URL is already known; if omitted, the channel is resolved automatically from the hololive official site's talent page at startup.

## Notes

Live status is determined by polling YouTube's `/live` page, which is unofficial scraping. It may stop working if YouTube changes its page structure.
