import time

# Official EN display names that don't follow the plain "slug -> Title Case"
# pattern (stylized capitalization, apostrophes, or a slug that abbreviates
# the real name).
EN_NAME_OVERRIDES = {
    "irys": "IRyS",
    "azki": "AZKi",
    "ninomae-inanis": "Ninomae Ina'nis",
    "la-darknesss": "Laplus Darknesss",
    "roboco-san": "Roboco-san",
    "achrora": "ACHRORA",
}

# Hardcoded (not locale/strftime-derived) so the world clock's weekday names
# stay in the selected in-app language regardless of the OS locale.
WEEKDAYS = {
    "ja": ["月", "火", "水", "木", "金", "土", "日"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


# Fixed UTC offsets (not zoneinfo/OS-tzdata based) so each label stays exactly
# what it says year-round instead of silently becoming e.g. EDT under DST.
# The third field is that country's own date field order, not the app
# language, so e.g. EST always reads month/day/year regardless of self.lang.
WORLD_CLOCK_ZONES = (
    ("JST", 9, "ymd"),   # Japan: year/month/day
    ("WIB", 7, "dmy"),   # Indonesia: day/month/year
    ("UTC", 0, "iso"),   # ISO 8601: year-month-day
    ("EST", -5, "mdy"),  # US Eastern: month/day/year
    ("PST", -8, "mdy"),  # US Pacific: month/day/year
)


def _format_zone_date(order, zoned):
    y, m, d = zoned.tm_year, zoned.tm_mon, zoned.tm_mday
    if order == "ymd":
        return f"{y}/{m:02d}/{d:02d}"
    if order == "dmy":
        return f"{d:02d}/{m:02d}/{y}"
    if order == "iso":
        return f"{y}-{m:02d}-{d:02d}"
    return f"{m:02d}/{d:02d}/{y}"


def format_world_clock(lang, now_epoch):
    # One (label, date, time) tuple per zone, date pre-formatted in that
    # zone's own country convention (with the app-language weekday appended)
    # for a 3-column x 2-row grid. tm_wday is Mon=0..Sun=6, matching the
    # order of WEEKDAYS[lang].
    entries = []
    for label, offset_hours, order in WORLD_CLOCK_ZONES:
        zoned = time.gmtime(now_epoch + offset_hours * 3600)
        weekday = WEEKDAYS[lang][zoned.tm_wday]
        date_part = f"{_format_zone_date(order, zoned)}({weekday})"
        time_part = f"{zoned.tm_hour:02d}:{zoned.tm_min:02d}:{zoned.tm_sec:02d}"
        entries.append((label, date_part, time_part))
    return entries

STRINGS = {
    "ja": {
        "title": "ホロライブ",
        "clock_category": "現在時刻",
        "pin": "最前面",
        "lang_toggle": "EN",
        "count": "配信中 {live}人 / 全{total}人",
        "legend_live": "配信中",
        "legend_idle": "待機中",
        "legend_error": "エラー",
        "bg_slider": "背景濃さ",
        "text_slider": "サイズ",
        "updated": "最終更新 {time}",
        "updated_none": "最終更新 --:--:--",
        "refresh": "更新",
        "refreshing": "更新中…",
        "close": "終了",
        "copy_name": "名前をコピー",
        "copy_title": "配信タイトルをコピー",
        "palette_hint": "色にカーソルを合わせる",
        "live_filter": "LIVE",
        "no_live": "配信中のタレントはいません",
        "dark_mode": "ダークモード",
        "light_mode": "ライトモード",
        "theme_color": "テーマカラー",
        "language": "言語",
        "lang_ja": "日本語",
        "lang_en": "English",
    },
    "en": {
        "title": "hololive",
        "clock_category": "Current Time",
        "pin": "TopMost",
        "lang_toggle": "日",
        "count": "{live} Live / {total} Total",
        "legend_live": "Live",
        "legend_idle": "Idle",
        "legend_error": "Error",
        "bg_slider": "BG",
        "text_slider": "Text",
        "updated": "Updated {time}",
        "updated_none": "Updated --:--:--",
        "refresh": "Refresh",
        "refreshing": "Refreshing…",
        "close": "Close",
        "copy_name": "Copy Name",
        "copy_title": "Copy Title",
        "palette_hint": "Hover a color",
        "live_filter": "LIVE",
        "no_live": "No one is live right now",
        "dark_mode": "Dark Mode",
        "light_mode": "Light Mode",
        "theme_color": "Theme Color",
        "language": "Language",
        "lang_ja": "日本語",
        "lang_en": "English",
    },
}


def english_name(slug):
    # talents.json has no dedicated English field, so derive a display name
    # from the (already-romanized) slug, patched by EN_NAME_OVERRIDES for the
    # handful that don't follow plain "word-word -> Word Word" casing.
    if slug in EN_NAME_OVERRIDES:
        return EN_NAME_OVERRIDES[slug]
    return " ".join(word.capitalize() for word in slug.split("-"))
