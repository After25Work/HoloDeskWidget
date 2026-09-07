---
name: release
description: Build and package a release zip for either variant this repo ships -- HoloDeskWidget (single-production, hololive-only) or VTDeskWidget (multi-production) -- for this repository. Use this whenever the user asks to release, ship, package, or build a distributable/production build of the widget, cut a new version, bump the version number, or wants the release_widget.bat / build_widget.bat scripts run. Also trigger on Japanese phrasing like "リリース", "パッケージ化", "配布用ビルド", "バージョンを上げる". Ask which variant (Holo or VT) if it isn't obvious from context. This is specific to this repository and keeps the version number in sync across all five files that hardcode it, per variant.
---

# HoloDeskWidget / VTDeskWidget release

This repo ships two variants of the same widget, built from a shared
`deskwidget_core/` engine: **Holo** (`variants/holo/`, single production --
hololive only) and **VT** (`variants/vt/`, eleven productions with a tab
strip and productions picker). Each has its own version number, its own
`release/<AppName>-v<version>.zip`, and is built/released independently --
**always confirm which variant the user means** before running anything if
it isn't already clear (they may want both).

This skill exists because each variant's version number is hardcoded as
literal text in five places (only one of which is actually read by the
running app), and it's easy to update one and forget the rest.

## Where the version lives (per variant)

Substitute `holo` or `vt` for `<variant>` below; the app name in the last
two rows is `HoloDeskWidget` for `holo`, `VTDeskWidget` for `vt`.

| File | What to look for |
|---|---|
| `variants/<variant>/version.py` | `__version__ = "x.y.z"` — the only one read at runtime (shown in the app's right-click menu) |
| `variants/<variant>/README.md` | `現在のバージョン: **x.y.z**` |
| `variants/<variant>/README.en.md` | `Current version: **x.y.z**` |
| `variants/<variant>/docs/Readme.html` | `<p class="subtitle">バージョン x.y.z</p>` and `<footer>{AppName} vx.y.z</footer>` |
| `variants/<variant>/docs/Readme.en.html` | `<p class="subtitle">Version x.y.z</p>` and `<footer>{AppName} vx.y.z</footer>` |

`docs/Readme.html` and `docs/Readme.en.html` are single-page manuals with
screenshots embedded as base64 (300-400KB, mostly one giant line per image).
**Never open these with a normal file read/rewrite** — that either fails
outright or burns huge amounts of context on image data you don't need to
see. Always change them via `scripts/bump_version.py`, which does a
targeted string replacement and asserts each match is unique before writing.

## Workflow

1. **Determine the variant and old/new version.** Read the current value
   straight out of `variants/<variant>/version.py` (a plain `Read` with a
   small line range is fine — that file is tiny). If the user gave an
   explicit new version, use it. If they said something relative ("bump the
   patch version", "release as-is" without a version bump), work out the new
   version yourself (semver: patch = last number +1, unless the changes
   since the last release clearly warrant a minor/major bump) or ask if it's
   ambiguous. If the user wants to package the **current** version with no
   bump, skip step 2 entirely.

2. **Sync the version everywhere**, from the repo root:
   ```bash
   python .claude/skills/release/scripts/bump_version.py <holo|vt> <old_version> <new_version>
   ```
   This touches all 5 of that variant's files in one atomic-ish pass and
   fails loudly (no partial write, and no downgrade -- <new_version> must be
   greater than <old_version>) if any expected string isn't found exactly
   once — that usually means the version was already bumped, or one of the
   files was hand-edited and drifted from the expected format. If it fails,
   open just that one file's relevant few lines (not the whole HTML file) to
   see what's actually there, fix the script's expected string or the file
   by hand, and retry.

3. **Run the release build.** This is a Windows batch file, so it must go
   through the **PowerShell tool**, not Bash, from the repo root:
   ```
   & ".\release_widget.bat" holo
   ```
   (or `vt` for the other variant). This calls `build_widget.bat <variant>`
   (PyInstaller, using `build/HoloDesk Widget.spec` or `build/VTDeskWidget.spec`)
   to produce `dist/HoloDesk Widget.exe` or `dist/VTDeskWidget.exe`, then
   stages the exe + that variant's `productions/` directory (+
   `clock_zones.json`, if that variant has one -- otherwise the app falls
   back to its in-code default zone table) + both
   `variants/<variant>/docs/Readme*.html` into
   `release/<AppName>-v<version>/`, zips it to
   `release/<AppName>-v<version>.zip`, and deletes the staging folder. It
   exits non-zero on build failure — if PyInstaller isn't installed it says
   so explicitly rather than failing obscurely.

4. **Verify the output.** Confirm the zip contains exactly what's expected
   and nothing else (no stray `settings.json`, no log files, no staging
   leftovers):
   ```bash
   unzip -l "release/HoloDeskWidget-v<version>.zip"
   ```
   Holo expects: `HoloDesk Widget.exe`, `productions/index.json`,
   `productions/hololive.json`, `clock_zones.json`, `Readme.html`,
   `Readme.en.html`.
   VT expects the same shape plus its other ten `productions/*.json` files
   and its own `clock_zones.json`.

5. **Hand off the artifact.** If a file-delivery tool is available (e.g.
   `SendUserFile`), send the zip so the user doesn't have to dig through
   `release/` themselves.

## What this skill deliberately does NOT do

- **No git operations.** It never commits, tags, or pushes. `build/`,
  `dist/`, and `release/` are all gitignored — they're disposable build
  output, not repo content. `variants/<variant>/version.py`,
  `variants/<variant>/README.md`, `variants/<variant>/README.en.md`, and the
  two `variants/<variant>/docs/Readme*.html` files *do* change on disk
  (tracked files), so after a successful release, tell the user those 5
  files changed and ask whether they want them committed — do not commit
  automatically.
- **No automatic version-number guessing without telling the user what you
  picked.** State the old → new version explicitly before running the
  build so a misread intent (patch vs. minor) is caught before it's baked
  into a release filename.
- **No cross-variant assumptions.** Bumping/releasing Holo never touches
  VT's files or vice versa — they version independently.
