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


def stage_replacement(pending: dict[Path, str], path: Path, old: str, new: str) -> None:
    text = pending.get(path)
    if text is None:
        text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"[FAIL] Expected exactly 1 match of {old!r} in {path}, found {count}. "
            "Aborting without writing any file -- check the file manually."
        )
    pending[path] = text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python bump_version.py <old_version> <new_version>")
    old, new = sys.argv[1], sys.argv[2]
    if old == new:
        raise SystemExit(f"[FAIL] old and new version are both {old!r} -- nothing to do.")

    # Every replacement is validated and staged in memory first; nothing is
    # written to disk until all 7 replacements across all 5 files succeed,
    # so a failure partway through never leaves the version strings
    # out of sync on disk.
    pending: dict[Path, str] = {}

    stage_replacement(pending, ROOT / "holowidget" / "version.py",
                       f'__version__ = "{old}"', f'__version__ = "{new}"')

    stage_replacement(pending, ROOT / "README.md",
                       f"現在のバージョン: **{old}**", f"現在のバージョン: **{new}**")

    stage_replacement(pending, ROOT / "README.en.md",
                       f"Current version: **{old}**", f"Current version: **{new}**")

    stage_replacement(pending, ROOT / "docs" / "Readme.html",
                       f'<p class="subtitle">バージョン {old}</p>',
                       f'<p class="subtitle">バージョン {new}</p>')
    stage_replacement(pending, ROOT / "docs" / "Readme.html",
                       f'<footer>HoloDeskWidget v{old}</footer>',
                       f'<footer>HoloDeskWidget v{new}</footer>')

    stage_replacement(pending, ROOT / "docs" / "Readme.en.html",
                       f'<p class="subtitle">Version {old}</p>',
                       f'<p class="subtitle">Version {new}</p>')
    stage_replacement(pending, ROOT / "docs" / "Readme.en.html",
                       f'<footer>HoloDeskWidget v{old}</footer>',
                       f'<footer>HoloDeskWidget v{new}</footer>')

    for path, text in pending.items():
        path.write_text(text, encoding="utf-8")
        print(f"[OK] {path.relative_to(ROOT)}")

    print(f"\nVersion bumped: {old} -> {new} (5 files, 7 replacements)")


if __name__ == "__main__":
    main()
