"""Sync the app version across every file that hardcodes it.

holowidget/version.py is the single source of truth (it's the only place
read at runtime, for the right-click menu). The other four files embed the
same string as static text for humans, so nothing keeps them in sync
automatically -- this script does that by targeted, asserted string
replacement instead of a blind find-and-replace, since docs/Readme*.html
are 300-400KB single-line-per-tag files (base64 screenshots inline) that
are impractical to open and re-save as a whole.

Usage:
    python bump_version.py <old_version> <new_version>

Every replacement asserts it matches exactly once before writing, so a
stale <old_version> argument (already bumped, or a typo) fails loudly
instead of silently corrupting a file or renaming the wrong occurrence.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"[FAIL] Expected exactly 1 match of {old!r} in {path}, found {count}. "
            "Aborting without writing -- check the file manually."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[OK] {path.relative_to(ROOT)}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python bump_version.py <old_version> <new_version>")
    old, new = sys.argv[1], sys.argv[2]
    if old == new:
        raise SystemExit(f"[FAIL] old and new version are both {old!r} -- nothing to do.")

    replace_once(ROOT / "holowidget" / "version.py",
                 f'__version__ = "{old}"', f'__version__ = "{new}"')

    replace_once(ROOT / "README.md",
                 f"現在のバージョン: **{old}**", f"現在のバージョン: **{new}**")

    replace_once(ROOT / "README.en.md",
                 f"Current version: **{old}**", f"Current version: **{new}**")

    replace_once(ROOT / "docs" / "Readme.html",
                 f'<p class="subtitle">バージョン {old}</p>',
                 f'<p class="subtitle">バージョン {new}</p>')
    replace_once(ROOT / "docs" / "Readme.html",
                 f'<footer>HoloDeskWidget v{old}</footer>',
                 f'<footer>HoloDeskWidget v{new}</footer>')

    replace_once(ROOT / "docs" / "Readme.en.html",
                 f'<p class="subtitle">Version {old}</p>',
                 f'<p class="subtitle">Version {new}</p>')
    replace_once(ROOT / "docs" / "Readme.en.html",
                 f'<footer>HoloDeskWidget v{old}</footer>',
                 f'<footer>HoloDeskWidget v{new}</footer>')

    print(f"\nVersion bumped: {old} -> {new} (5 files, 7 replacements)")


if __name__ == "__main__":
    main()
