import calendar

from deskwidget_core import strings


# -- STRINGS i18n key parity ----------------------------------------------

def test_all_languages_define_the_same_keys():
    ja_keys = set(strings.STRINGS["ja"])
    en_keys = set(strings.STRINGS["en"])

    assert ja_keys == en_keys


def test_weekdays_defined_for_every_supported_language():
    for lang in strings.STRINGS:
        assert lang in strings.WEEKDAYS
        assert len(strings.WEEKDAYS[lang]) == 7


# -- _nth_sunday / _last_sunday --------------------------------------------

def test_nth_sunday_matches_calendar_for_known_month():
    # March 2024: Sundays fall on 3, 10, 17, 24, 31.
    assert strings._nth_sunday(2024, 3, 1) == calendar.datetime.date(2024, 3, 3)
    assert strings._nth_sunday(2024, 3, 2) == calendar.datetime.date(2024, 3, 10)


def test_last_sunday_matches_known_month():
    # October 2024's last Sunday is the 27th.
    assert strings._last_sunday(2024, 10) == calendar.datetime.date(2024, 10, 27)


def test_last_sunday_handles_december_year_rollover():
    # December 2024's last Sunday is the 29th; exercises the year+1 branch.
    assert strings._last_sunday(2024, 12) == calendar.datetime.date(2024, 12, 29)


# -- US DST window (2nd Sunday of March -> 1st Sunday of November) ----------

def test_us_dst_inactive_just_before_start(monkeypatch):
    # 2024 US DST starts 2024-03-10 02:00 local standard time (EST, UTC-5).
    start_utc, end_utc = strings._dst_window_us(2024, -5)

    assert strings._is_dst_active("us", -5, start_utc - 1) is False
    assert strings._is_dst_active("us", -5, start_utc) is True


def test_us_dst_inactive_at_and_after_end(monkeypatch):
    _, end_utc = strings._dst_window_us(2024, -5)

    assert strings._is_dst_active("us", -5, end_utc - 1) is True
    assert strings._is_dst_active("us", -5, end_utc) is False


# -- EU DST window (last Sunday of March/October, 01:00 UTC) -----------------

def test_eu_dst_boundaries():
    start_utc, end_utc = strings._dst_window_eu(2024, 1)

    assert strings._is_dst_active("eu", 1, start_utc - 1) is False
    assert strings._is_dst_active("eu", 1, start_utc) is True
    assert strings._is_dst_active("eu", 1, end_utc - 1) is True
    assert strings._is_dst_active("eu", 1, end_utc) is False


def test_is_dst_active_false_for_unknown_rule():
    assert strings._is_dst_active("mars", 0, 0) is False


# -- _load_dst_rule -----------------------------------------------------------

def test_load_dst_rule_returns_none_when_absent():
    assert strings._load_dst_rule({}) is None


def test_load_dst_rule_returns_none_for_malformed_entries():
    assert strings._load_dst_rule({"dst": "not-a-dict"}) is None
    assert strings._load_dst_rule({"dst": {"rule": "unknown", "offset_hours": 1, "label": "X"}}) is None
    assert strings._load_dst_rule({"dst": {"rule": "us", "offset_hours": "one", "label": "X"}}) is None
    assert strings._load_dst_rule({"dst": {"rule": "us", "offset_hours": 1, "label": 123}}) is None


def test_load_dst_rule_parses_valid_entry():
    assert strings._load_dst_rule({"dst": {"rule": "us", "offset_hours": 1, "label": "PDT"}}) == ("us", 1, "PDT")


# -- _format_zone_date --------------------------------------------------------

def test_format_zone_date_orders():
    zoned = calendar.datetime.datetime(2024, 3, 5, 6, 7, 8).timetuple()

    assert strings._format_zone_date("ymd", zoned) == "2024/03/05"
    assert strings._format_zone_date("dmy", zoned) == "05/03/2024"
    assert strings._format_zone_date("iso", zoned) == "2024-03-05"
    assert strings._format_zone_date("mdy", zoned) == "03/05/2024"


# -- format_world_clock --------------------------------------------------------

def test_format_world_clock_returns_one_entry_per_zone():
    now_epoch = calendar.timegm((2024, 6, 15, 12, 0, 0))

    entries = strings.format_world_clock("en", now_epoch)

    assert len(entries) == len(strings.WORLD_CLOCK_ZONES)
    for label, date_part, time_part in entries:
        assert isinstance(label, str) and label
        assert isinstance(date_part, str) and "(" in date_part
        assert len(time_part) == 8  # HH:MM:SS


def test_format_world_clock_switches_to_dst_label_in_summer():
    # Mid-July is inside both US and EU DST windows.
    now_epoch = calendar.timegm((2024, 7, 15, 12, 0, 0))

    entries = strings.format_world_clock("en", now_epoch)
    labels = [label for label, _, _ in entries]

    assert any("PDT" in label for label in labels)
    assert any("CEST" in label for label in labels)


def test_format_world_clock_uses_standard_label_in_winter():
    now_epoch = calendar.timegm((2024, 1, 15, 12, 0, 0))

    entries = strings.format_world_clock("en", now_epoch)
    labels = [label for label, _, _ in entries]

    assert any(label.startswith("PST") for label in labels)
    assert any(label.startswith("CET") for label in labels)
    assert not any("PDT" in label for label in labels)
