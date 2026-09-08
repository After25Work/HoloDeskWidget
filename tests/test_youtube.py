from urllib.error import HTTPError

import pytest

from deskwidget_core import youtube


@pytest.fixture(autouse=True)
def clear_channel_id_cache():
    youtube._channel_id_cache.clear()
    youtube._channel_id_locks.clear()
    yield
    youtube._channel_id_cache.clear()
    youtube._channel_id_locks.clear()


def _http_error(code):
    return HTTPError("https://example.com", code, "err", {}, None)


# -- is_stale_channel_error -------------------------------------------------

def test_is_stale_channel_error_true_for_channel_not_found():
    assert youtube.is_stale_channel_error(youtube.ChannelNotFoundError("x")) is True


def test_is_stale_channel_error_true_for_http_404():
    assert youtube.is_stale_channel_error(_http_error(404)) is True


def test_is_stale_channel_error_false_for_other_http_codes():
    assert youtube.is_stale_channel_error(_http_error(500)) is False


def test_is_stale_channel_error_false_for_unrelated_exception():
    assert youtube.is_stale_channel_error(ValueError("x")) is False


# -- build_search_fallback_url -----------------------------------------------

def test_build_search_fallback_url_quotes_the_name():
    url = youtube.build_search_fallback_url("Tokino Sora")

    assert url == "https://www.youtube.com/results?search_query=hololive+Tokino+Sora"


# -- resolve_channel_url ------------------------------------------------------

def test_resolve_channel_url_prefers_handle_over_channel_id(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: (
        '<a href="https://www.youtube.com/@talent-a">link</a>'
        '<a href="https://www.youtube.com/channel/UCabc123">also</a>'
    ))

    assert youtube.resolve_channel_url("talent-a") == "https://www.youtube.com/@talent-a"


def test_resolve_channel_url_ignores_hololive_own_handle(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: (
        '<a href="https://www.youtube.com/@hololive">official</a>'
        '<a href="https://www.youtube.com/@talent-a">link</a>'
    ))

    assert youtube.resolve_channel_url("talent-a") == "https://www.youtube.com/@talent-a"


def test_resolve_channel_url_falls_back_to_channel_id(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: (
        '<a href="https://www.youtube.com/channel/UCabc123">link</a>'
    ))

    assert youtube.resolve_channel_url("talent-a") == "https://www.youtube.com/channel/UCabc123"


def test_resolve_channel_url_ignores_hololive_shared_channel_id(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: (
        '<a href="https://www.youtube.com/channel/UCJFZiqLMntJufDCHc6bQixg">shared</a>'
    ))

    with pytest.raises(ValueError):
        youtube.resolve_channel_url("talent-a")


def test_resolve_channel_url_raises_when_nothing_found(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: "<html>no links here</html>")

    with pytest.raises(ValueError):
        youtube.resolve_channel_url("talent-a")


# -- _resolve_channel_id -------------------------------------------------------

def test_resolve_channel_id_extracts_from_channel_url_without_network():
    channel_id = youtube._resolve_channel_id("https://www.youtube.com/channel/UCabc123")

    assert channel_id == "UCabc123"


def test_resolve_channel_id_fetches_and_caches_for_handle_url(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return '{"externalId":"UCxyz789"}'

    monkeypatch.setattr(youtube, "_get", fake_get)

    first = youtube._resolve_channel_id("https://www.youtube.com/@talent-a")
    second = youtube._resolve_channel_id("https://www.youtube.com/@talent-a")

    assert first == "UCxyz789"
    assert second == "UCxyz789"
    assert len(calls) == 1  # second call served from cache, no re-fetch


def test_resolve_channel_id_prefers_external_id_over_channel_id(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: (
        '"channelId":"UCwrong000","externalId":"UCcorrect111"'
    ))

    assert youtube._resolve_channel_id("https://www.youtube.com/@talent-a") == "UCcorrect111"


def test_resolve_channel_id_falls_back_to_channel_id_field(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: '"channelId":"UConly222"')

    assert youtube._resolve_channel_id("https://www.youtube.com/@talent-a") == "UConly222"


def test_resolve_channel_id_raises_and_does_not_cache_on_failure(monkeypatch):
    monkeypatch.setattr(youtube, "_get", lambda url, timeout: "<html>nothing</html>")

    with pytest.raises(ValueError):
        youtube._resolve_channel_id("https://www.youtube.com/@talent-a")

    assert "https://www.youtube.com/@talent-a" not in youtube._channel_id_cache


def test_invalidate_channel_id_removes_cached_entry():
    youtube._channel_id_cache["https://x/@a"] = "UC1"

    youtube._invalidate_channel_id("https://x/@a")

    assert "https://x/@a" not in youtube._channel_id_cache


# -- _has_error_alert -----------------------------------------------------------

def test_has_error_alert_true_when_error_alert_present():
    data = {"alerts": [{"alertRenderer": {"type": "ERROR"}}]}

    assert youtube._has_error_alert(data) is True


def test_has_error_alert_false_when_no_alerts():
    assert youtube._has_error_alert({}) is False


def test_has_error_alert_handles_null_alerts_list():
    assert youtube._has_error_alert({"alerts": None}) is False


def test_has_error_alert_handles_null_entries_and_null_renderer():
    data = {"alerts": [None, {"alertRenderer": None}, {"alertRenderer": {"type": "INFO"}}]}

    assert youtube._has_error_alert(data) is False


# -- _parse_live_tab ------------------------------------------------------------

def _lockup(content_id="video123", title="Stream title", is_live=True, has_thumbnail=True):
    badge_style = "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE" if is_live else "THUMBNAIL_OVERLAY_BADGE_STYLE_DEFAULT"
    lockup = {"contentId": content_id}
    if has_thumbnail:
        lockup["contentImage"] = {
            "thumbnailViewModel": {
                "overlays": [
                    {"thumbnailBottomOverlayViewModel": {
                        "badges": [{"thumbnailBadgeViewModel": {"badgeStyle": badge_style}}]
                    }}
                ]
            }
        }
    if title is not None:
        lockup["metadata"] = {"lockupMetadataViewModel": {"title": {"content": title}}}
    return lockup


def _browse_response(lockups):
    return {
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {"tabRenderer": {"selected": False, "content": {}}},
                    {"tabRenderer": {"selected": True, "content": {"richGridRenderer": {"contents": [
                        {"richItemRenderer": {"content": {"lockupViewModel": lockup}}} for lockup in lockups
                    ]}}}},
                ]
            }
        }
    }


def test_parse_live_tab_returns_none_when_nothing_live():
    data = _browse_response([_lockup(is_live=False)])

    assert youtube._parse_live_tab(data) == (None, None)


def test_parse_live_tab_returns_video_id_and_title_for_live_entry():
    data = _browse_response([_lockup(content_id="abc", title="My stream", is_live=True)])

    assert youtube._parse_live_tab(data) == ("abc", "My stream")


def test_parse_live_tab_skips_pinned_upcoming_item_and_finds_later_live_one():
    upcoming = _lockup(content_id="upcoming1", is_live=False)
    live = _lockup(content_id="live2", title="Actually live", is_live=True)

    data = _browse_response([upcoming, live])

    assert youtube._parse_live_tab(data) == ("live2", "Actually live")


def test_parse_live_tab_skips_live_badged_entry_missing_content_id():
    incomplete = _lockup(content_id=None, is_live=True)
    incomplete["contentId"] = None
    complete = _lockup(content_id="ok1", title="Ok", is_live=True)

    data = _browse_response([incomplete, complete])

    assert youtube._parse_live_tab(data) == ("ok1", "Ok")


def test_parse_live_tab_handles_missing_title():
    data = _browse_response([_lockup(content_id="abc", title=None, is_live=True)])

    assert youtube._parse_live_tab(data) == ("abc", None)


def test_parse_live_tab_returns_none_on_unexpected_shape():
    assert youtube._parse_live_tab({"contents": {}}) == (None, None)


def test_parse_live_tab_returns_none_when_no_lockup_present():
    data = _browse_response([{}])
    # Overwrite with a richItemRenderer lacking lockupViewModel entirely.
    data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][1]["tabRenderer"]["content"][
        "richGridRenderer"]["contents"] = [{"richItemRenderer": {"content": {}}}]

    assert youtube._parse_live_tab(data) == (None, None)


# -- fetch_live_info (network mocked) ------------------------------------------

def test_fetch_live_info_returns_live_video(monkeypatch):
    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", lambda url, payload, timeout: _browse_response(
        [_lockup(content_id="v1", title="t", is_live=True)]))

    assert youtube.fetch_live_info("https://www.youtube.com/channel/UCabc") == ("v1", "t")


def test_fetch_live_info_raises_channel_not_found_and_invalidates_cache(monkeypatch):
    youtube._channel_id_cache["https://x"] = "UCabc"
    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", lambda url, payload, timeout: {
        "alerts": [{"alertRenderer": {"type": "ERROR"}}]
    })

    with pytest.raises(youtube.ChannelNotFoundError):
        youtube.fetch_live_info("https://x")

    assert "https://x" not in youtube._channel_id_cache


def test_fetch_live_info_retries_once_on_missing_contents_then_succeeds(monkeypatch):
    responses = iter([{"no_contents_here": True}, _browse_response([_lockup(content_id="v1", is_live=True)])])
    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", lambda url, payload, timeout: next(responses))

    assert youtube.fetch_live_info("https://x") == ("v1", "Stream title")


def test_fetch_live_info_gives_up_as_not_live_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", lambda url, payload, timeout: {"no_contents_here": True})

    assert youtube.fetch_live_info("https://x") == (None, None)


def test_fetch_live_info_respects_attempts_argument(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, payload, timeout):
        call_count["n"] += 1
        return {"no_contents_here": True}

    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", fake_post)

    youtube.fetch_live_info("https://x", attempts=1)

    assert call_count["n"] == 1


def test_fetch_live_info_invalidates_cache_on_http_404(monkeypatch):
    youtube._channel_id_cache["https://x"] = "UCabc"
    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")

    def raise_404(url, payload, timeout):
        raise _http_error(404)

    monkeypatch.setattr(youtube, "_post_json", raise_404)

    with pytest.raises(HTTPError):
        youtube.fetch_live_info("https://x")

    assert "https://x" not in youtube._channel_id_cache


# -- _post_json / resolve_watch_page_url ---------------------------------------

class _FakeResponse:
    def __init__(self, body, geturl_result=None):
        self._body = body.encode("utf-8")
        self._geturl_result = geturl_result

    def read(self):
        return self._body

    def geturl(self):
        return self._geturl_result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_post_json_raises_value_error_on_non_object_response(monkeypatch):
    monkeypatch.setattr(youtube, "_open", lambda *a, **k: _FakeResponse("[1, 2, 3]"))

    with pytest.raises(ValueError):
        youtube._post_json("https://x", {}, 5)


def test_resolve_watch_page_url_strips_live_suffix(monkeypatch):
    monkeypatch.setattr(youtube, "_open", lambda *a, **k: _FakeResponse(
        "", geturl_result="https://www.youtube.com/@talent/live"))

    assert youtube.resolve_watch_page_url("https://www.youtube.com/@talent") == "https://www.youtube.com/@talent"


def test_fetch_live_info_retries_on_transient_os_error(monkeypatch):
    calls = {"n": 0}

    def flaky_post(url, payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("timeout")
        return _browse_response([_lockup(content_id="v1", is_live=True)])

    monkeypatch.setattr(youtube, "_resolve_channel_id", lambda url, timeout: "UCabc")
    monkeypatch.setattr(youtube, "_post_json", flaky_post)

    assert youtube.fetch_live_info("https://x") == ("v1", "Stream title")
    assert calls["n"] == 2
