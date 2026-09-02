import json
import re
import threading
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _open(url, timeout, data=None, extra_headers=None):
    request = Request(url, data=data, headers={**_HEADERS, **(extra_headers or {})})
    return urlopen(request, timeout=timeout)


def _get(url, timeout):
    with _open(url, timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _post_json(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    with _open(url, timeout, data=body, extra_headers={"Content-Type": "application/json"}) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def resolve_channel_url(slug):
    profile = _get(f"https://hololive.hololivepro.com/talents/{slug}/", 20)
    handles = [handle for handle in dict.fromkeys(re.findall(
        r"https?://(?:www\.)?youtube\.com/@([A-Za-z0-9_.-]+)", profile
    )) if handle.lower() != "hololive"]
    if handles:
        return f"https://www.youtube.com/@{handles[0]}"
    channels = re.findall(r"https://www\.youtube\.com/channel/(UC[\w-]+)", profile)
    channels = [channel for channel in dict.fromkeys(channels)
                if channel != "UCJFZiqLMntJufDCHc6bQixg"]
    if not channels:
        raise ValueError(f"YouTube channel was not found for {slug}")
    return f"https://www.youtube.com/channel/{channels[0]}"


# Public web-client API key embedded in every youtube.com page's ytcfg (not a
# secret credential) — needed to call the same internal "browse" endpoint the
# site's own web client uses to render a channel's Live tab.
_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
# Opaque protobuf selecting a channel's "Live" tab; same constant the web
# client sends when a viewer clicks that tab.
_LIVE_TAB_PARAMS = "EgdzdHJlYW1z8gYECgJ6AA=="
# YouTube periodically stops honoring innertube requests tagged with an old
# enough client version. If fetch_live_info() starts failing, or silently
# returning no live data for every channel, check this first: open
# youtube.com, view page source, search for "INNERTUBE_CONTEXT_CLIENT_VERSION"
# and paste in the current value.
_CLIENT_VERSION = "2.20240101.00.00"
# The channel-id lookup is a single lightweight page fetch (read one id out
# of embedded page data), not the heavier browse call fetch_live_info()
# itself retries at up to `timeout` each — a much shorter timeout still
# comfortably covers it, and keeps a slow/uncached first-time lookup (only
# handle-style channel_urls need this; see _resolve_channel_id()) from
# adding as much to the worst-case refresh latency. Used as a cap via
# min(timeout, _RESOLVE_TIMEOUT) so a caller-supplied timeout shorter than
# this is still honored.
_RESOLVE_TIMEOUT = 10


def fetch_live_info(channel_url, timeout=20):
    # Raises HTTPError/OSError/UnicodeError/ValueError on failure so the
    # caller can tell "couldn't check" apart from "checked, and it's not
    # live" (returns (None, None)); returns the stream's current title too
    # (for the live-only view's ticker) when one is live.
    #
    # This used to scrape /live's server-rendered HTML for playabilityStatus,
    # but YouTube now answers that page for high-traffic live streams with a
    # "Sign in to confirm you're not a bot" LOGIN_REQUIRED interstitial
    # instead of the real player data — silently misreporting an actually
    # live channel as offline (it's a 200 OK with no error to catch). The
    # channel's "Live" tab, fetched through the same internal JSON endpoint
    # the web client itself calls to render that tab, isn't subject to that
    # gate and carries an explicit LIVE badge on the current broadcast.
    channel_id = _resolve_channel_id(channel_url, timeout)
    url = f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_KEY}"
    payload = {
        "context": {"client": {"clientName": "WEB", "clientVersion": _CLIENT_VERSION}},
        "browseId": channel_id,
        "params": _LIVE_TAB_PARAMS,
    }
    # One retry against a fresh request: an occasional truncated/incomplete
    # response from this endpoint shouldn't read as "not live" for a whole
    # 60s refresh cycle when trying again right away usually clears it. A
    # 404 (bad/renamed channel id) is left alone here — check_one() in
    # widget.py already has its own re-resolve-and-retry path for that.
    for attempt in range(2):
        try:
            data = _post_json(url, payload, timeout)
        except HTTPError:
            raise
        except (OSError, ValueError):
            if attempt == 1:
                raise
            continue
        if _has_error_alert(data):
            # A bad/renamed browseId doesn't fail the HTTP request itself
            # (this endpoint answers with 200 OK and an "alerts" ERROR
            # banner, e.g. "This channel does not exist."), unlike the old
            # /live scrape which 404'd directly. Synthesize the same 404
            # check_one() in widget.py already re-resolves-and-retries on,
            # so that recovery path still fires instead of the channel
            # silently reading as "offline" forever. Also evict the cached
            # channel_id for this channel_url: without this, check_one()'s
            # retry re-resolves the same channel_url (stable for handle-based
            # talents, the common case) and _resolve_channel_id() would just
            # hand back the same bad id from cache, making that retry a
            # no-op that fails identically forever instead of actually
            # re-fetching a fresh id.
            _invalidate_channel_id(channel_url)
            raise HTTPError(url, 404, "channel not found", None, None)
        if "contents" in data:
            break
        # A syntactically valid response that's simply missing the expected
        # "contents" shape is this endpoint's analogue of the old /live
        # scrape's client-hydration "shell" page — retry once against a
        # fresh request rather than trusting it as "not live" outright.
    return _parse_live_tab(data)


def _has_error_alert(data):
    return any(
        # `data.get("alerts", [])` alone isn't enough: that default only
        # applies when the key is absent, and this endpoint can send an
        # explicit "alerts": null, which would make `for alert in None`
        # raise TypeError instead of just finding no ERROR alert. Individual
        # entries can likewise be null, so guard each one the same way rather
        # than letting `alert.get(...)` raise AttributeError.
        (alert or {}).get("alertRenderer", {}).get("type") == "ERROR"
        for alert in (data.get("alerts") or [])
    )


_channel_id_cache = {}
# Guards _channel_id_cache: check_one() in widget.py runs one daemon thread
# per talent, and if two talents ever share a channel_url (e.g. a collab
# channel), concurrent first-time lookups would otherwise both miss the
# cache and race on the same read-fetch-write sequence below.
_channel_id_cache_lock = threading.Lock()


def _invalidate_channel_id(channel_url):
    with _channel_id_cache_lock:
        _channel_id_cache.pop(channel_url, None)


def _resolve_channel_id(channel_url, timeout=_RESOLVE_TIMEOUT):
    with _channel_id_cache_lock:
        if channel_url in _channel_id_cache:
            return _channel_id_cache[channel_url]
    match = re.search(r"/channel/(UC[\w-]+)", channel_url)
    if match:
        channel_id = match.group(1)
    else:
        # A handle-style URL (e.g. .../@hololive) has no UC id in it, so
        # fetch the channel page once to read it out of the embedded page
        # data. Cached below since a channel's id never changes: without
        # this, every 60s refresh would re-fetch this page for every
        # handle-based talent — the common case, see resolve_channel_url()
        # — forever, doubling steady-state request volume for no benefit.
        # A failed lookup (raises ValueError below) is never cached, so
        # it's retried on the next refresh instead of getting stuck failing.
        html = _get(channel_url, min(timeout, _RESOLVE_TIMEOUT))
        # "externalId" (the page's own channel metadata) is unique per page
        # and always identifies the channel being viewed. "channelId"
        # appears many times over — featured/related-channel shelves, other
        # members of the same unit, etc. — so searching for it first can
        # latch onto some other channel entirely (e.g. a talent's page
        # listing their group's shared channel before their own metadata
        # block). Prefer externalId; only fall back to channelId if a page
        # ever omits it.
        match = re.search(r'"externalId"\s*:\s*"(UC[\w-]+)"', html)
        if not match:
            match = re.search(r'"channelId"\s*:\s*"(UC[\w-]+)"', html)
        if not match:
            raise ValueError(f"Could not resolve channel id for {channel_url}")
        channel_id = match.group(1)
    with _channel_id_cache_lock:
        _channel_id_cache[channel_url] = channel_id
    return channel_id


def _parse_live_tab(data):
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        # Matched by "selected" (this is the one tab the request's `params`
        # asked for) rather than title text: the client context here sends
        # no explicit hl/gl, so the tab title isn't guaranteed to be the
        # literal English string "Live" for every request.
        live_tab = next(
            tab["tabRenderer"] for tab in tabs
            if tab.get("tabRenderer", {}).get("selected")
        )
        items = live_tab["content"]["richGridRenderer"]["contents"]
        # The channel's most recent broadcasts — live, upcoming, or already
        # ended — in some YouTube-chosen order that isn't reliably "live
        # first": a pinned recurring "free chat" premiere can sit at index 0
        # as "Upcoming" while the actual live broadcast is further down. So
        # scan for the first entry with a LIVE-styled thumbnail badge rather
        # than assuming items[0] is it; a scheduled stream gets a different
        # ("Upcoming") badge style instead.
        for item in items:
            lockup = item.get("richItemRenderer", {}).get("content", {}).get("lockupViewModel")
            if not lockup:
                continue
            content_image = lockup.get("contentImage") or {}
            thumbnail_view_model = content_image.get("thumbnailViewModel") or {}
            overlays = thumbnail_view_model.get("overlays") or []
            is_live = any(
                (badge or {}).get("thumbnailBadgeViewModel", {}).get("badgeStyle")
                == "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE"
                for overlay in overlays
                for badge in (overlay or {}).get("thumbnailBottomOverlayViewModel", {}).get("badges", [])
            )
            if not is_live:
                continue
            # `.get(key, {})` only falls back to {} when the key is absent —
            # any of these can also be explicitly null, which would make the
            # next .get() in the chain raise AttributeError. Use `or {}`
            # instead so a null anywhere in this chain degrades to title =
            # None rather than raising into the broad except below, which
            # would otherwise wipe out the is_live result already confirmed
            # above just because of a missing/null title field.
            metadata = lockup.get("metadata") or {}
            title_obj = (metadata.get("lockupMetadataViewModel") or {}).get("title") or {}
            title = title_obj.get("content")
            return lockup.get("contentId"), title
        return None, None
    except (KeyError, TypeError, StopIteration, AttributeError):
        # Any nested lookup above can come back missing, or present but
        # explicitly null, for a response shape this parser doesn't
        # recognize — treat that the same as "not live" rather than letting
        # it kill the calling worker thread (see check_one() in widget.py).
        return None, None


def resolve_watch_page_url(channel_url, timeout=5):
    # Follows a channel's /live redirect to the concrete watch-page URL it
    # currently points at (live or not) — used to open the "closest" link
    # available when a cached live URL isn't on hand yet. Needs the response
    # object itself (for geturl()), not just its decoded body, so this uses
    # _open() directly instead of _get().
    with _open(channel_url.rstrip("/") + "/live", timeout) as response:
        return response.geturl().removesuffix("/live")


def build_search_fallback_url(name):
    return ("https://www.youtube.com/results?search_query="
            + quote_plus(f"hololive {name}"))
