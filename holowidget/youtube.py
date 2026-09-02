import functools
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url, timeout):
    request = Request(url, headers=_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _post_json(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={**_HEADERS, "Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
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
_LIVE_TAB_PARAMS = "EgdzdHJlYW1z8gYECgJ6AA%3D%3D"
# YouTube periodically stops honoring innertube requests tagged with an old
# enough client version. If fetch_live_info() starts failing, or silently
# returning no live data for every channel, check this first: open
# youtube.com, view page source, search for "INNERTUBE_CONTEXT_CLIENT_VERSION"
# and paste in the current value.
_CLIENT_VERSION = "2.20240101.00.00"


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
            break
        except HTTPError:
            raise
        except (OSError, ValueError):
            if attempt == 1:
                raise
    return _parse_live_tab(data)


@functools.lru_cache(maxsize=None)
def _resolve_channel_id(channel_url, timeout):
    match = re.search(r"/channel/(UC[\w-]+)", channel_url)
    if match:
        return match.group(1)
    # A handle-style URL (e.g. .../@hololive) has no UC id in it, so fetch
    # the channel page once to read it out of the embedded page data. Cached
    # (see the decorator) since a channel's id never changes: without this,
    # every 60s refresh would re-fetch this page for every handle-based
    # talent — the common case, see resolve_channel_url() — forever,
    # doubling steady-state request volume for no benefit. A failed lookup
    # (raises ValueError below) is never cached, so it's retried on the next
    # refresh instead of getting stuck failing.
    html = _get(channel_url, timeout)
    # "externalId" (the page's own channel metadata) is unique per page and
    # always identifies the channel being viewed. "channelId" appears many
    # times over — featured/related-channel shelves, other members of the
    # same unit, etc. — so searching for it first can latch onto some other
    # channel entirely (e.g. a talent's page listing their group's shared
    # channel before their own metadata block). Prefer externalId; only fall
    # back to channelId if a page ever omits it.
    match = re.search(r'"externalId"\s*:\s*"(UC[\w-]+)"', html)
    if not match:
        match = re.search(r'"channelId"\s*:\s*"(UC[\w-]+)"', html)
    if not match:
        raise ValueError(f"Could not resolve channel id for {channel_url}")
    return match.group(1)


def _parse_live_tab(data):
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        live_tab = next(
            tab["tabRenderer"] for tab in tabs
            if tab.get("tabRenderer", {}).get("title") == "Live"
        )
        items = live_tab["content"]["richGridRenderer"]["contents"]
        if not items:
            return None, None
        # The first item is the channel's most recent broadcast — live, upcoming,
        # or already ended. Only a LIVE-styled thumbnail badge means it's
        # actually broadcasting right now; a scheduled stream gets a different
        # ("Upcoming") badge style instead.
        lockup = items[0].get("richItemRenderer", {}).get("content", {}).get("lockupViewModel")
        if not lockup:
            return None, None
        overlays = lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", [])
        is_live = any(
            badge.get("thumbnailBadgeViewModel", {}).get("badgeStyle") == "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE"
            for overlay in overlays
            for badge in overlay.get("thumbnailBottomOverlayViewModel", {}).get("badges", [])
        )
        if not is_live:
            return None, None
        title = (lockup.get("metadata", {})
                 .get("lockupMetadataViewModel", {})
                 .get("title", {})
                 .get("content"))
        return lockup.get("contentId"), title
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
    # object itself (for geturl()), not just its body, so this doesn't go
    # through _get().
    request = Request(channel_url.rstrip("/") + "/live", headers=_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return response.geturl().removesuffix("/live")


def build_search_fallback_url(name):
    return ("https://www.youtube.com/results?search_query="
            + quote_plus(f"hololive {name}"))
