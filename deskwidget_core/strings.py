import calendar
import datetime
import json
import time

from .paths import ROOT

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


# Fixed UTC offsets (not zoneinfo/OS-tzdata based), each optionally paired
# with a DST rule, so a zone with no "dst" entry stays exactly what it says
# year-round while one that does observe summer time (e.g. US Eastern) still
# switches label/offset automatically. The third field is that country's own
# date field order, not the app language, so e.g. EST always reads
# month/day/year regardless of self.lang. The 5th/6th fields are the
# representative city/region name shown alongside the abbreviation, in
# Japanese and English respectively.
# Ships as clock_zones.json (user-editable, no code change needed to
# add/remove/relabel a zone) with these same 8 zones, spread across the globe
# roughly every 3 hours; this tuple is only the in-code fallback if that file
# is ever missing/corrupt. The 4th field is (rule, extra_offset_hours,
# dst_label) or None — see _DST_WINDOWS for the supported rules.
_DEFAULT_CLOCK_ZONES = (
    ("HST", -10, "mdy", None, "ハワイ", "Hawaii"),
    ("PST", -8, "mdy", ("us", 1, "PDT"), "ロサンゼルス", "Los Angeles"),
    ("EST", -5, "mdy", ("us", 1, "EDT"), "ニューヨーク", "New York"),
    ("UTC", 0, "iso", None, "UTC", "UTC"),
    ("CET", 1, "dmy", ("eu", 1, "CEST"), "中央ヨーロッパ", "Central Europe"),
    ("GST", 4, "dmy", None, "ドバイ", "Dubai"),
    ("WIB", 7, "dmy", None, "ジャカルタ", "Jakarta"),
    ("JST", 9, "ymd", None, "東京", "Tokyo"),
)


def _nth_sunday(year, month, n):
    # n=1..4 for the nth Sunday of the month. date.weekday() is Mon=0..Sun=6,
    # matching the tm_wday convention used throughout this module.
    first = datetime.date(year, month, 1)
    first_sunday = first + datetime.timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + datetime.timedelta(days=7 * (n - 1))


def _last_sunday(year, month):
    first_next = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    last_day = first_next - datetime.timedelta(days=1)
    return last_day - datetime.timedelta(days=(last_day.weekday() + 1) % 7)


def _dst_window_us(year, offset_hours):
    # US rule: 2nd Sunday of March 02:00 local standard time to 1st Sunday of
    # November 02:00 local daylight time (= 01:00 standard) -> clocks jump at
    # the same wall-clock hour, so the UTC instant depends on the offset.
    start = _nth_sunday(year, 3, 2)
    end = _nth_sunday(year, 11, 1)
    start_utc = calendar.timegm((start.year, start.month, start.day, 2, 0, 0)) - offset_hours * 3600
    end_utc = calendar.timegm((end.year, end.month, end.day, 1, 0, 0)) - offset_hours * 3600
    return start_utc, end_utc


def _dst_window_eu(year, offset_hours):
    # EU rule: last Sunday of March/October, both at 01:00 UTC exactly (the
    # same instant everywhere), independent of the zone's own offset.
    start = _last_sunday(year, 3)
    end = _last_sunday(year, 10)
    start_utc = calendar.timegm((start.year, start.month, start.day, 1, 0, 0))
    end_utc = calendar.timegm((end.year, end.month, end.day, 1, 0, 0))
    return start_utc, end_utc


_DST_WINDOWS = {"us": _dst_window_us, "eu": _dst_window_eu}


def _is_dst_active(rule, offset_hours, now_epoch):
    window_fn = _DST_WINDOWS.get(rule)
    if window_fn is None:
        return False
    # The DST window is computed per calendar year, so pick the year from the
    # zone's standard-offset local time (not raw UTC) to avoid resolving to
    # the wrong year's window near midnight UTC on Jan 1st/31st.
    year = time.gmtime(now_epoch + offset_hours * 3600).tm_year
    start_utc, end_utc = window_fn(year, offset_hours)
    return start_utc <= now_epoch < end_utc


def _load_dst_rule(zone):
    dst = zone.get("dst")
    if not isinstance(dst, dict):
        return None
    rule, dst_offset, dst_label = dst.get("rule"), dst.get("offset_hours"), dst.get("label")
    if rule not in _DST_WINDOWS or not isinstance(dst_offset, (int, float)) or not isinstance(dst_label, str):
        return None
    return (rule, dst_offset, dst_label)


def _load_clock_zones():
    try:
        data = json.loads((ROOT / "clock_zones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _DEFAULT_CLOCK_ZONES
    zones = [
        (zone["label"], zone["offset_hours"], zone["date_order"], _load_dst_rule(zone),
         zone.get("name_ja", zone["label"]), zone.get("name_en", zone["label"]))
        for zone in (data if isinstance(data, list) else [])
        if isinstance(zone, dict) and "label" in zone and "offset_hours" in zone
        and zone.get("date_order") in ("ymd", "dmy", "iso", "mdy")
    ]
    # Sorted by standard-time offset descending (furthest-ahead zone first)
    # so the world clock always reads left-to-right/top-to-bottom in that
    # order, regardless of what order zones happen to be listed in
    # clock_zones.json (the file is user-editable, so its order isn't
    # guaranteed to already match).
    zones.sort(key=lambda zone: zone[1], reverse=True)
    return zones or _DEFAULT_CLOCK_ZONES


# Loaded once at startup, same timing as the productions/ talent lists (no
# live-reload while the widget is running).
WORLD_CLOCK_ZONES = _load_clock_zones()


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
    # One (label, date, time) tuple per zone, label suffixed with that zone's
    # representative city/region name (in the current app language, in
    # parentheses) so the abbreviation alone doesn't have to carry the
    # meaning. Date is pre-formatted in that zone's own country convention
    # (with the app-language weekday appended) for a 3-column grid. tm_wday
    # is Mon=0..Sun=6, matching the order of WEEKDAYS[lang].
    entries = []
    for label, offset_hours, order, dst, name_ja, name_en in WORLD_CLOCK_ZONES:
        name = name_ja if lang == "ja" else name_en
        if dst is not None and _is_dst_active(dst[0], offset_hours, now_epoch):
            label, offset_hours = dst[2], offset_hours + dst[1]
        zoned = time.gmtime(now_epoch + offset_hours * 3600)
        weekday = WEEKDAYS[lang][zoned.tm_wday]
        date_part = f"{_format_zone_date(order, zoned)}({weekday})"
        time_part = f"{zoned.tm_hour:02d}:{zoned.tm_min:02d}:{zoned.tm_sec:02d}"
        # Skip the redundant suffix for a zone whose region name already
        # equals its abbreviation (e.g. UTC).
        display_label = label if name == label else f"{label}({name})"
        entries.append((display_label, date_part, time_part))
    return entries

STRINGS = {
    "ja": {
        "clock_category": "現在時刻",
        "pin": "最前面",
        "fullscreen": "全画面表示",
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
        "no_talents": "タレントが登録されていません",
        "dark_mode": "ダークモード",
        "light_mode": "ライトモード",
        "theme_color": "テーマカラー",
        "font_family": "フォント",
        "font_hint": "フォント名で検索",
        "language": "言語",
        "lang_ja": "日本語",
        "lang_en": "English",
        "productions_button": "表示",
        "productions_hint": "表示するプロダクション",
        "productions_enable_all": "全て有効",
        "productions_disable_all": "全て無効",
        "tray_minimize": "トレイに格納",
        "tray_show": "表示",
        "tray_exit": "終了",
        "stream_history": "配信履歴",
        "stream_start": "配信開始",
        "stream_end": "配信終了",
        "stream_history_today": "本日の配信開始: {count}件",
        "stream_history_empty": "履歴はまだありません",
        "stream_history_hint": "ダブルクリックでYouTubeを開く",
    },
    "en": {
        "clock_category": "Current Time",
        "pin": "TopMost",
        "fullscreen": "Fullscreen",
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
        "no_talents": "No talents registered",
        "dark_mode": "Dark Mode",
        "light_mode": "Light Mode",
        "theme_color": "Theme Color",
        "font_family": "Font",
        "font_hint": "Search fonts",
        "language": "Language",
        "lang_ja": "日本語",
        "lang_en": "English",
        "productions_button": "Show",
        "productions_hint": "Productions to show",
        "productions_enable_all": "Enable All",
        "productions_disable_all": "Disable All",
        "tray_minimize": "Minimize to Tray",
        "tray_show": "Show",
        "tray_exit": "Exit",
        "stream_history": "Stream History",
        "stream_start": "Live Start",
        "stream_end": "Live End",
        "stream_history_today": "Today's live starts: {count}",
        "stream_history_empty": "No history yet",
        "stream_history_hint": "Double-click to open on YouTube",
    },
}


def english_name(slug):
    # A production's talent-list JSON has no dedicated English field, so
    # derive a display name from the (already-romanized) slug, patched by
    # EN_NAME_OVERRIDES for the handful that don't follow plain
    # "word-word -> Word Word" casing.
    if slug in EN_NAME_OVERRIDES:
        return EN_NAME_OVERRIDES[slug]
    return " ".join(word.capitalize() for word in slug.split("-"))
