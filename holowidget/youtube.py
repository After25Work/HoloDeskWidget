import json
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


def resolve_channel_url(slug):
    profile_url = f"https://hololive.hololivepro.com/talents/{slug}/"
    request = Request(profile_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        profile = response.read().decode("utf-8", errors="ignore")
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


def fetch_live_video_id(channel_url, timeout=20):
    # Raises HTTPError/OSError/UnicodeError/ValueError on failure so the
    # caller can tell "couldn't check" apart from "checked, and it's not
    # live" (returns None).
    return fetch_live_info(channel_url, timeout)[0]


def fetch_live_info(channel_url, timeout=20):
    # Same failure semantics as fetch_live_video_id(), plus the stream's
    # current title (for the live-only view's ticker) when one is live.
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
    body = json.dumps({
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00"}},
        "browseId": channel_id,
        "params": _LIVE_TAB_PARAMS,
    }).encode("utf-8")
    request = Request(
        f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_KEY}",
        data=body,
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="ignore"))
    return _parse_live_tab(data)


def _resolve_channel_id(channel_url, timeout):
    match = re.search(r"/channel/(UC[\w-]+)", channel_url)
    if match:
        return match.group(1)
    # A handle-style URL (e.g. .../@hololive) has no UC id in it, so fetch
    # the channel page once to read it out of the embedded page data.
    request = Request(channel_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    match = re.search(r'"(?:channelId|externalId)"\s*:\s*"(UC[\w-]+)"', html)
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
    except (KeyError, TypeError, StopIteration):
        return None, None
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


def resolve_watch_page_url(channel_url, timeout=5):
    # Follows a channel's /live redirect to the concrete watch-page URL it
    # currently points at (live or not) — used to open the "closest" link
    # available when a cached live URL isn't on hand yet.
    request = Request(channel_url.rstrip("/") + "/live", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.geturl().removesuffix("/live")


def build_search_fallback_url(name):
    return ("https://www.youtube.com/results?search_query="
            + quote_plus(f"hololive {name}"))
