import ctypes
import functools
import os
import struct
from ctypes import wintypes
from pathlib import Path

from PIL import ImageFont

_FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# Always tried after whatever family the user picked, so a missing/corrupt
# file for that pick -- or a pick that's since been uninstalled -- still
# renders Japanese text instead of falling back to Pillow's non-CJK bitmap
# default. Meiryo and MS Gothic ship as single .ttc files with no separate
# bold/regular weight, so they reuse the same file for both bold values.
_FALLBACK_CANDIDATES = {
    True: ("YuGothM.ttc", "meiryob.ttc", "msgothic.ttc"),
    False: ("YuGothR.ttc", "meiryo.ttc", "msgothic.ttc"),
}
DEFAULT_FONT_FAMILY = "Yu Gothic"

_FONT_FILE_SUFFIXES = (".ttf", ".ttc", ".otf")
# Preferred style name per bucket, most-preferred first, used to pick one
# representative face when a family has several non-bold (or several bold)
# faces at different weights -- e.g. Yu Gothic ships Light/Medium/Regular
# non-bold faces across separate .ttc files, and directory iteration order
# isn't alphabetical, so without this the arbitrarily-first-seen one (which
# could be "Light") would win over the actual "Regular" face.
_REGULAR_STYLE_PREFERENCE = ("Regular", "Normal", "Book", "Medium")
_BOLD_STYLE_PREFERENCE = ("Bold",)


# 'あ' (U+3042) -- any font that can render Japanese at all ships the
# Hiragana block, while Latin-only fonts (Arial, Segoe UI, ...) don't, so
# checking for this one codepoint is enough to tell the two apart without
# hand-parsing per-script ranges.
_HIRAGANA_PROBE_CODEPOINT = 0x3042

# Windows LCID values used to pick a family's localized name out of its
# 'name' table -- e.g. Yu Gothic's Microsoft-platform name records carry
# "Yu Gothic" under 0x0409 and "游ゴシック" under 0x0411. Pillow/FreeType's
# getname() (used as the family's identity everywhere else in this module)
# only ever surfaces one of these, so the font picker's display text is
# read straight out of the file instead.
_LANG_ID_EN_US = 0x0409
_LANG_ID_JA_JP = 0x0411
_NAME_ID_FAMILY = 1


class _LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", ctypes.c_long),
        ("lfWidth", ctypes.c_long),
        ("lfEscapement", ctypes.c_long),
        ("lfOrientation", ctypes.c_long),
        ("lfWeight", ctypes.c_long),
        ("lfItalic", ctypes.c_byte),
        ("lfUnderline", ctypes.c_byte),
        ("lfStrikeOut", ctypes.c_byte),
        ("lfCharSet", ctypes.c_byte),
        ("lfOutPrecision", ctypes.c_byte),
        ("lfClipPrecision", ctypes.c_byte),
        ("lfQuality", ctypes.c_byte),
        ("lfPitchAndFamily", ctypes.c_byte),
        ("lfFaceName", ctypes.c_wchar * 32),
    ]


class _GLYPHSET(ctypes.Structure):
    _fields_ = [
        ("cbThis", wintypes.DWORD),
        ("flAccel", wintypes.DWORD),
        ("cGlyphsSupported", wintypes.DWORD),
        ("cRanges", wintypes.DWORD),
    ]


@functools.lru_cache(maxsize=None)
def _supports_japanese(family_name):
    # Asks GDI what Unicode ranges the family actually covers
    # (GetFontUnicodeRanges) instead of guessing from the family name --
    # some fonts with Western-sounding names ship Japanese glyphs and some
    # with Japanese-sounding names don't cover the ranges we'd assume.
    gdi32 = ctypes.windll.gdi32
    hdc = gdi32.CreateDCW("DISPLAY", None, None, None)
    if not hdc:
        return False
    logfont = _LOGFONTW()
    try:
        # lfFaceName is a fixed WCHAR[32] (LF_FACESIZE) -- GDI can't address
        # a family by a name that doesn't fit in it anyway, so treat one
        # that's too long the same as "can't check, assume no Japanese"
        # rather than letting ctypes' ValueError crash the font picker.
        logfont.lfFaceName = family_name
    except ValueError:
        return False
    hfont = gdi32.CreateFontIndirectW(ctypes.byref(logfont))
    old_font = gdi32.SelectObject(hdc, hfont)
    try:
        size = gdi32.GetFontUnicodeRanges(hdc, None)
        if not size:
            return False
        buf = ctypes.create_string_buffer(size)
        if not gdi32.GetFontUnicodeRanges(hdc, ctypes.cast(buf, ctypes.POINTER(_GLYPHSET))):
            return False
        glyphset = _GLYPHSET.from_buffer(buf)
        # The GLYPHSET header is followed by cRanges packed WCRANGE entries
        # {wcLow: WORD, cGlyphs: WORD}, each naming one contiguous run of
        # supported codepoints starting at wcLow.
        offset = ctypes.sizeof(_GLYPHSET)
        for _ in range(glyphset.cRanges):
            low, count = struct.unpack_from("<HH", buf.raw, offset)
            offset += 4
            if low <= _HIRAGANA_PROBE_CODEPOINT < low + count:
                return True
        return False
    finally:
        gdi32.SelectObject(hdc, old_font)
        gdi32.DeleteObject(hfont)
        gdi32.DeleteDC(hdc)


def _style_rank(style, is_bold):
    preference = _BOLD_STYLE_PREFERENCE if is_bold else _REGULAR_STYLE_PREFERENCE
    try:
        return preference.index(style)
    except ValueError:
        return len(preference)


def _font_dirs():
    dirs = [_FONTS_DIR]
    # Windows 10+ lets a font be installed "for me only" (no admin), which
    # lands here instead of the machine-wide Fonts folder above.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        user_dir = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
        if user_dir.is_dir():
            dirs.append(user_dir)
    return dirs


@functools.lru_cache(maxsize=None)
def _scan_installed_fonts():
    # Resolved once per process (not re-scanned on every font-picker open):
    # a font installed/removed mid-session is a rare enough edge case that
    # requiring a restart to see it isn't worth re-scanning every time.
    #
    # Family/style names come from each font FILE's own name table (via
    # Pillow/FreeType's getname()) rather than parsed out of Windows'
    # registry display names -- those are "&"-joined per-file summaries
    # (e.g. the registry literally names one entry "Yu Gothic Medium & Yu
    # Gothic UI Regular (TrueType)" for a single file) that don't cleanly
    # split back into the families Windows itself treats as separate ("Yu
    # Gothic" vs "Yu Gothic UI"), where reading the files directly does. A
    # .ttc can bundle several faces (e.g. Yu Gothic + Yu Gothic UI, at
    # several weights each), so every face index is probed until loading
    # one fails. The face index is kept alongside the path (not just the
    # path) so _display_names_by_family() below can re-open the exact same
    # face's own 'name' table rather than always reading face 0 of a .ttc.
    families = {}  # family name -> {is_bold: (rank, path, index)}
    for directory in _font_dirs():
        try:
            paths = [p for p in directory.iterdir() if p.suffix.lower() in _FONT_FILE_SUFFIXES]
        except OSError:
            continue
        for path in paths:
            index = 0
            while True:
                try:
                    face = ImageFont.truetype(str(path), 10, index=index)
                except OSError:
                    break
                current_index = index
                index += 1
                family, style = face.getname()
                is_bold = "bold" in (style or "").lower()
                rank = _style_rank(style, is_bold)
                bucket = families.setdefault(family, {})
                if is_bold not in bucket or rank < bucket[is_bold][0]:
                    bucket[is_bold] = (rank, path, current_index)
    return families


@functools.lru_cache(maxsize=None)
def list_installed_fonts():
    families = _scan_installed_fonts()
    result = []
    for family in sorted(families, key=str.casefold):
        # The picker should only offer fonts that can actually render the
        # talent names / titles it's used for -- a Latin-only family
        # selected by mistake would silently fall back to whatever
        # _FALLBACK_CANDIDATES picks for Japanese text anyway, so excluding
        # it here keeps the picker's choices meaningful.
        if not _supports_japanese(family):
            continue
        styles = families[family]
        regular = styles.get(False, styles.get(True))[1]
        bold = styles.get(True, styles.get(False))[1]
        result.append((family, {True: bold, False: regular}))
    return result


@functools.lru_cache(maxsize=None)
def _installed_fonts_by_name():
    return dict(list_installed_fonts())


def _read_family_names(path, index):
    # Manually walks the TrueType/OpenType 'name' table (sfnt directory ->
    # 'name' table -> NameRecords) instead of using a library: Pillow's
    # ImageFont/FreeType only ever exposes ONE family name per face (via
    # getname(), already used as this module's identity for the family),
    # picked by FreeType's own platform/language preference, with no way to
    # ask it for a specific language's record instead. A .ttc's per-face
    # tables are located via the ttcf header's offset array; a plain
    # .ttf/.otf has no such header and its table directory starts at 0.
    try:
        data = path.read_bytes()
        offset = 0
        if data[:4] == b"ttcf":
            num_fonts = struct.unpack_from(">I", data, 8)[0]
            if not 0 <= index < num_fonts:
                index = 0
            offset = struct.unpack_from(">I", data, 12 + 4 * index)[0]
        num_tables = struct.unpack_from(">H", data, offset + 4)[0]
        name_table_offset = None
        record_offset = offset + 12
        for _ in range(num_tables):
            tag = data[record_offset:record_offset + 4]
            if tag == b"name":
                name_table_offset = struct.unpack_from(">I", data, record_offset + 8)[0]
                break
            record_offset += 16
        if name_table_offset is None:
            return {}
        count, string_offset = struct.unpack_from(">HH", data, name_table_offset + 2)
        storage_start = name_table_offset + string_offset
        names = {}
        record_offset = name_table_offset + 6
        for _ in range(count):
            platform_id, _encoding_id, language_id, name_id, length, str_offset = (
                struct.unpack_from(">HHHHHH", data, record_offset))
            record_offset += 12
            if platform_id == 3 and name_id == _NAME_ID_FAMILY:
                raw = data[storage_start + str_offset:storage_start + str_offset + length]
                names[language_id] = raw.decode("utf-16-be")
        return names
    except (OSError, struct.error, UnicodeDecodeError, IndexError):
        # Truncated/corrupt file, or a layout this hand-rolled parser
        # doesn't understand -- the caller falls back to the family's
        # existing (language-agnostic) identity name.
        return {}


@functools.lru_cache(maxsize=None)
def _display_names_by_family():
    scanned = _scan_installed_fonts()
    result = {}
    for family, _files in list_installed_fonts():
        entry = scanned[family].get(False, scanned[family].get(True))
        _rank, path, index = entry
        names = _read_family_names(path, index)
        en = names.get(_LANG_ID_EN_US)
        ja = names.get(_LANG_ID_JA_JP)
        result[family] = {"en": en or ja or family, "ja": ja or en or family}
    return result


def family_display_name(family, lang):
    # Falls back to the family's own identity name (whatever
    # list_installed_fonts() surfaced it as) for a family this process
    # hasn't scanned, or a font file with no localized name for `lang`.
    return _display_names_by_family().get(family, {}).get(lang, family)


# Family name every font()/_font_paths() call should prefer, ahead of
# _FALLBACK_CANDIDATES. Module-level (not threaded through every font() call
# site) since font() is already called from ~15 places in widget.py with
# just (size, bold) -- set_font_family() below is the single place that
# changes it, and it clears both caches so the switch takes effect
# immediately.
_current_family_name = DEFAULT_FONT_FAMILY


def set_font_family(name):
    global _current_family_name
    if name != _current_family_name:
        _current_family_name = name
        _font_paths.cache_clear()
        font.cache_clear()


def get_font_family():
    return _current_family_name


@functools.lru_cache(maxsize=None)
def _font_paths(bold):
    # Resolved once per bold value (there are only two) instead of inside
    # font(): font() is cached per (size, bold), and the UI's label auto-fit
    # search calls it with many distinct sizes, so without this a missing
    # font file would be re-probed via failed ImageFont.truetype() OSErrors
    # on every new size instead of just once. Cleared by set_font_family()
    # whenever the selected family changes, since the ordering below depends
    # on _current_family_name at the time this was cached.
    # Returns every candidate that EXISTS, not just the first: font() below
    # still needs to try each in turn, since a candidate can exist on disk
    # but fail to actually load (corrupt/partial install), and only file
    # existence is checked here.
    ordered_paths = []
    seen = set()
    selected = _installed_fonts_by_name().get(_current_family_name)
    if selected is not None:
        path = selected.get(bold, selected.get(not bold))
        if path is not None:
            ordered_paths.append(path)
            seen.add(path)
    for filename in _FALLBACK_CANDIDATES[bold]:
        path = _FONTS_DIR / filename
        if path not in seen:
            seen.add(path)
            ordered_paths.append(path)
    # A tuple, not a list: lru_cache hands back this same object on every
    # call for a given `bold`, and a mutable list would let a future caller
    # that mutates its result (e.g. .pop()) permanently corrupt the cache.
    return tuple(path for path in ordered_paths if path.exists())


@functools.lru_cache(maxsize=None)
def font(size, bold=True):
    for path in _font_paths(bold):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            # This candidate exists but doesn't actually load (corrupt or
            # unsupported file) — try the next candidate in the fallback
            # chain instead of jumping straight to the bitmap default below.
            continue
    # None of the known CJK-capable fonts are present or loadable. Fall back
    # to Pillow's built-in font rather than letting the OSError propagate and
    # crash startup — Japanese glyphs won't render, but a degraded UI beats a
    # hard failure the caller (widget.py draws through this everywhere) has
    # no way to work around.
    return ImageFont.load_default(size=size)


@functools.lru_cache(maxsize=None)
def emoji_font(size):
    # Yu Gothic has no emoji glyphs, so emoji in live titles need Segoe UI
    # Emoji instead. It's a color bitmap font with fixed strike sizes;
    # FreeType scales to the nearest one and Pillow renders it via
    # ImageDraw.text(..., embedded_color=True).
    try:
        return ImageFont.truetype(str(_FONTS_DIR / "seguiemj.ttf"), size)
    except OSError:
        return None
