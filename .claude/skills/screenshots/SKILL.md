---
name: screenshots
description: Refresh HoloDeskWidget's documentation screenshots/GIF (main.png, buttons.png, context_menu.png, live_ticker.gif, plus their _en counterparts) in variants/holo/docs/screenshots/, captured against the app's default settings.json state rather than whatever a developer's local window position/theme/language happens to be. Use whenever the user asks to update, refresh, retake, or regenerate the screenshots or the live ticker GIF, or "スクリーンショットを更新" / "スクショ撮り直し" and similar Japanese phrasing. Windows-only and Holo-variant-only (VT isn't wired up yet); moves the real mouse and briefly swaps the desktop wallpaper, so confirm with the user before running and ask them not to touch the mouse/keyboard while it's in progress.
---

# HoloDeskWidget screenshot refresh

`tools/capture_screenshots.py` (see its own docstring for full detail) already
launches or attaches to the widget, drives it with real mouse/keyboard input,
and saves `main`/`buttons`/`context_menu` (+ `_en`) plus `live_ticker.gif`
into `variants/holo/docs/screenshots/`. Left on its own it captures whatever
`variants/holo/settings.json` currently holds -- which for a developer
running the app locally is very likely *not* the default window
position/theme/language that `docs/Readme.html` is meant to depict.

This skill runs that script wrapped so the capture always reflects
`deskwidget_core.config.DEFAULT_SETTINGS`, then puts the developer's own
`settings.json` back exactly as it was.

`tools/capture_screenshots.py` picked up three fixes the first time this
skill actually ran end to end:

- **DPI awareness** (`SetProcessDpiAwareness`, called before any
  window/screen coordinate is touched) -- harmless and correct regardless,
  though it turned out not to be the real cause of the bleed below.
- **Desktop icons hidden for the duration** (`hidden_desktop_icons`, toggled
  the same way the Desktop right-click menu's "Show desktop icons" does).
  This was the actual cause: the widget's default position is `x=40, y=40`
  (see `DEFAULT_SETTINGS` in `deskwidget_core/config.py`) -- right on top of
  Windows' default top-left desktop icon grid. `frozen_desktop` only ever
  swapped the *wallpaper image*; icons are a separate layer Explorer always
  draws on top of it, so they showed straight through the widget's
  transparent rounded corners in every shot regardless of the wallpaper
  fix. Only restores icon visibility on exit if it actually hid them (a
  no-op if the user already had icons hidden).
- **A red always-on-top warning banner** pinned across the very top of the
  screen (y=0..32, safely above the widget's y=40 default top edge so it can
  never bleed into a grabbed region itself) reading "自動操作でスクリーンショット
  を撮影中です。完了するまでマウス・キーボードに触れないでください。" for the whole
  capture -- the script drives the real mouse/keyboard for ~20-40s and
  someone at the machine needs an obvious, on-screen cue beyond terminal
  output they may not be looking at.

## Before running

- **Confirm with the user first.** This takes over the real mouse cursor,
  right-clicks and clicks buttons on the actual desktop, and briefly swaps
  the wallpaper to a flat color (restored after). Tell them roughly what
  will happen and ask them not to use the mouse/keyboard until it's done
  (well under a minute).
- **Holo only.** `tools/capture_screenshots.py` is hardcoded to the Holo
  variant (`variants/holo/...`). If the user asks for VT screenshots, say
  that the capture script would need to be re-pointed at `variants/vt`
  first (its own docstring names the constants: `PROFILE`, `LAUNCH_SCRIPT`,
  `OUT_DIR`) -- that's a code change beyond what this skill does on its own;
  ask before making it.
- Must run on Windows in a normal interactive desktop session (not a
  remote/headless one) -- this repo's environment already is one.

## Running it

From the repo root, via the **PowerShell tool** (not Bash) -- it's driving a
real GUI on the interactive desktop, same reasoning as `release_widget.bat`
in the release skill:

```
python .claude\skills\screenshots\scripts\refresh_screenshots.py
```

This wrapper (`.claude/skills/screenshots/scripts/refresh_screenshots.py`):

1. Closes any HoloDeskWidget instance already running, so a stale process
   holding old settings in memory can't shadow the reset below.
2. Moves `variants/holo/settings.json` aside (if present) so the next
   launch falls back to `DEFAULT_SETTINGS` whole-cloth.
3. Runs `tools/capture_screenshots.py`, which launches the widget fresh,
   waits for its initial live-status refresh to settle, captures the
   Japanese shots, captures the live-only ticker GIF, switches to English
   and captures those, then switches back to Japanese.
4. Closes the instance it started.
5. Restores the original `settings.json` untouched (or deletes the file
   again if there wasn't one to begin with) -- the developer's own local
   window position/theme/language/etc. are never permanently changed.

If it fails partway through, the `finally` block still closes the widget and
restores `settings.json` -- check the printed output for which step failed.

## After running

- Report which files under `variants/holo/docs/screenshots/` changed
  (`git status` or `git diff --stat` on that directory).
- `live_ticker.gif` only shows visible scrolling if at least one tracked
  talent is actually live with a long enough title at capture time -- if it
  looks static, say so and offer to re-run.
- **This does not touch `variants/holo/docs/Readme.html` /
  `Readme.en.html`.** Those embed screenshots as inline base64 and nothing
  in this repo re-generates that embedding automatically (see the release
  skill's notes on those files) -- updating the PNGs/GIF alone is the whole
  scope of this skill. If the user also wants the manual pages' embedded
  copies refreshed, that's a separate, currently-manual step -- flag it
  rather than attempting it.
- These screenshot files are tracked in git (unlike `settings.json`, which
  is gitignored) -- after confirming the new shots look right, tell the user
  they changed and ask whether to commit, same as the release skill does for
  its version-bump files. Don't commit automatically.
