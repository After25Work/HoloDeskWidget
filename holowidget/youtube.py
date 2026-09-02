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


def fetch_live_video_id(channel_url, timeout=20):
    # Raises HTTPError/OSError/UnicodeError on failure so the caller can tell
    # "couldn't check" (e.g. a 404 worth retrying against a re-resolved
    # channel) apart from "checked, and it's not live" (returns None).
    return fetch_live_info(channel_url, timeout)[0]


def fetch_live_info(channel_url, timeout=20, attempts=2):
    # Same failure semantics as fetch_live_video_id(), plus the stream's
    # current title (for the live-only view's ticker) when one is live.
    #
    # YouTube intermittently answers /live with a client-hydration "shell"
    # page instead of the normal server-rendered watch page: it carries a
    # <link rel="canonical" href="undefined"> and omits the actual player
    # data, so there's nothing to find even when the channel is live. A
    # same-process retry lands on the normal rendered page far more often
    # than not, so retry once before concluding "not live" from a response
    # that never had the data to begin with.
    html = None
    for attempt in range(max(attempts, 1)):
        request = Request(channel_url.rstrip("/") + "/live", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
        if not re.search(r'<link rel="canonical" href="undefined"', html):
            break
    return _parse_live_info(html)


def _parse_live_info(html):
    # videoDetails.isLive is where this used to be read from, but current
    # /live responses often omit it entirely (or bury it deep past a
    # multi-KB shortDescription, well outside any reasonable search window)
    # while still including it truthfully for waiting-room "premieres in
    # N seconds" pages, which aren't actually live yet. playabilityStatus.
    # status is the one field that reliably distinguishes "playing right
    # now" (OK) from "scheduled/ended" (LIVE_STREAM_OFFLINE) in every
    # response shape observed, and it sits right before videoDetails.
    status = re.search(r'"playabilityStatus"\s*:\s*\{\s*"status"\s*:\s*"OK"', html)
    if not status:
        return None, None
    video = re.search(r'"videoId"\s*:\s*"([\w-]{6,})"', html[status.start():status.start() + 2_000])
    if not video:
        return None, None
    # The video's title lives in videoDetails, but that can sit well past
    # streamingData's adaptiveFormats list — dozens of googlevideo.com URLs,
    # easily 50KB+ for a live stream — so search forward for videoDetails
    # itself rather than assuming a fixed-size window reaches it.
    title = None
    details = re.search(r'"videoDetails"\s*:\s*\{', html[status.end():])
    if details:
        window_start = status.end() + details.start()
        details_window = html[window_start:window_start + 20_000]
        # status == "OK" alone doesn't distinguish a live broadcast from an
        # ordinary playable video (e.g. /live can keep pointing at a stream's
        # own watch page for a while after it ends, which is "OK" too). When
        # videoDetails explicitly says isLive: false, trust that over status.
        if re.search(r'"isLive"\s*:\s*false', details_window):
            return None, None
        title_match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', details_window)
        if title_match:
            try:
                title = json.loads(f'"{title_match.group(1)}"')
            except ValueError:
                title = None
    return video.group(1), title


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
