"""Background refresh machinery: kicking off per-talent worker threads,
resolving/caching each talent's channel URL, and fetching live status from
YouTube. Runs off the Tk main thread (see refresh_worker()'s note), only ever
touching self.production_data[prod_id] directly rather than the
active-tab-relative self.targets/self.states/etc. properties.
"""
import re
import threading
import time
import tkinter as tk
import webbrowser
from urllib.error import HTTPError

from . import youtube
from .paths import log_error
from .talents import ALL_PRODUCTION_ID

# Some live titles borrow standalone combining marks/syllabics from scripts
# no installed font here (Yu Gothic/Meiryo/MS Gothic/Segoe UI Emoji) has
# glyphs for — Thai/Lao tone marks used without a base letter (e.g. "☾ ໋"),
# and Unified Canadian Aboriginal Syllabics (e.g. ".ᐟ.ᐟ") — purely as
# decoration rather than to write actual Thai/Lao/Canadian-syllabics text.
# Rendered as-is these come out as tofu boxes, so they're stripped from
# titles entirely; see also the VARIATION SELECTOR-15 strip below for the
# same "known decoration our fonts can't render" reasoning.
_UNSUPPORTED_DECORATION_RE = re.compile(
    "[\U00000E31\U00000E34-\U00000E3A\U00000E47-\U00000E4E"
    "\U00000EB1\U00000EB4-\U00000EBC\U00000EC8-\U00000ECD"
    "\U00001400-\U0000167F\U000018B0-\U000018FF]+"
)


class RefreshMixin:
    def open_target(self, target):
        name, _, url, _ = target
        now = time.monotonic()
        if self.last_opened[0] == name and now - self.last_opened[1] < 0.5:
            return
        self.last_opened = (name, now)
        if self.states.get(name) == "live" and self.live_urls.get(name):
            webbrowser.open(self.live_urls[name], new=2)
            return
        # check_one() may have already resolved a better URL than the production's
        # JSON guess; prefer that cached copy over the (possibly stale) tuple field.
        url = self.channel_urls.get(name, url)
        if "/channel/" in url:
            webbrowser.open(url, new=2)
            return
        # Resolve off the Tk main thread: this is a network call and click() runs
        # on the UI thread, so doing it inline would freeze the whole window.
        threading.Thread(target=self._resolve_and_open, args=(name, url), daemon=True).start()

    @staticmethod
    def _resolve_and_open(name, url):
        try:
            webbrowser.open(youtube.resolve_watch_page_url(url), new=2)
        except (HTTPError, OSError, ValueError):
            webbrowser.open(youtube.build_search_fallback_url(name), new=2)

    def refresh(self):
        if self.refresh_in_progress:
            return
        prod_id = self.active_production
        self.refresh_in_progress = True
        self.render()  # show the "refreshing" button state right away, not
                       # whenever the next tick/ticker render happens to land
        threading.Thread(target=self.refresh_worker, args=(prod_id,), daemon=True).start()

    def refresh_worker(self, prod_id):
        try:
            # ALL_PRODUCTION_ID has no slot/manifest entry of its own — refresh
            # every real production's slot instead, each against its own
            # manifest's auto_resolve, so switching to the "All" tab keeps
            # every talent (not just the previously-active production's) live.
            if prod_id == ALL_PRODUCTION_ID:
                # Slots for every visible production always exist by now --
                # set_production_enabled() (main thread) creates one on the
                # spot whenever a production is turned back on, the same way
                # switch_production() does when the "All" tab is entered --
                # so this can read production_data directly without racing a
                # lazy _production_slot() create from this background thread.
                jobs = [(self.production_data[production["id"]], production.get("auto_resolve"))
                        for production in self._visible_productions()]
            else:
                jobs = [(self.production_data[prod_id], self._productions_by_id[prod_id].get("auto_resolve"))]
            # Plain daemon threads instead of ThreadPoolExecutor: its worker
            # threads register with concurrent.futures' own atexit hook and
            # get joined before the interpreter is allowed to exit, so a
            # single slow/hanging youtube.fetch_live_info() call — which can
            # stack multiple 20s-timeout network requests (channel-id
            # resolution, an internal retry on the browse call, and this
            # module's own 404 channel re-resolve path) well past a single
            # 20s bound — would keep the whole process — and the
            # single-instance mutex it holds — alive well after the window
            # closes. Daemon threads are simply abandoned on exit instead.
            semaphore = threading.Semaphore(12)

            def bounded_check(slot, auto_resolve, name, target):
                with semaphore:
                    self.check_one(slot, auto_resolve, name, target)

            workers = [threading.Thread(target=bounded_check, args=(slot, auto_resolve, name, target), daemon=True)
                       for slot, auto_resolve in jobs
                       for name, _, target, _ in slot["targets"]]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        finally:
            try:
                self.root.after(0, self.refresh_complete, prod_id)
            except (RuntimeError, tk.TclError):
                # The window can be closed while a refresh is still in flight;
                # self.root is already destroyed at that point, nothing to update.
                pass

    def refresh_complete(self, prod_id):
        self.refresh_in_progress = False
        if prod_id == self.active_production:
            self.last_updated = time.strftime("%H:%M:%S")
            self.render()
            self.root.after(60_000, self.refresh)
        else:
            # The user switched tabs while this (now-stale) production's
            # refresh was still in flight — kick an immediate refresh for
            # whatever's active now instead of waiting out this one's 60s
            # cycle. That refresh's own refresh_complete() schedules the
            # next periodic tick, so this doesn't create a second loop.
            self.refresh()

    def check_one(self, slot, auto_resolve, name, target):
        # Operates on the explicit `slot` dict (self.production_data[prod_id])
        # rather than the self.targets/self.states/etc. properties, which
        # always reflect whichever production is active_production *right
        # now* — see the note above those properties. `auto_resolve` is the
        # owning production's manifest field: only "hololivepro" scrapes
        # hololive's official talent pages for a channel URL; every other
        # production (including custom) uses `target` (channel_url from its
        # JSON) as-is and never attempts a hololive-site re-resolve.
        targets, states, channel_urls, live_urls, live_titles = (
            slot["targets"], slot["states"], slot["channel_urls"],
            slot["live_urls"], slot["live_titles"])
        try:
            slug = next(slug for target_name, slug, _, _ in targets
                        if target_name == name)
            if auto_resolve == "hololivepro" and name not in channel_urls:
                try:
                    channel_urls[name] = youtube.resolve_channel_url(slug)
                except (HTTPError, OSError, UnicodeError, ValueError):
                    channel_urls[name] = target
            elif name not in channel_urls:
                channel_urls[name] = target
            target = channel_urls[name]
            try:
                video_id, title = youtube.fetch_live_info(target)
            except (HTTPError, youtube.ChannelNotFoundError) as error:
                # A ChannelNotFoundError (fetch_live_info() raises this when
                # the browse API answers 200 OK with an "alerts" ERROR banner
                # — a stale/bad browseId) and a genuine transport
                # HTTPError(404) mean the same thing to this retry: re-resolve
                # the channel and try once more. Any other HTTPError code is
                # a real failure, not one this retry can do anything about.
                # Only hololive has a known site to re-resolve against — any
                # other production just keeps last-known state on a stale
                # channel instead of scraping the wrong site.
                if not youtube.is_stale_channel_error(error) or auto_resolve != "hololivepro":
                    raise
                try:
                    target = youtube.resolve_channel_url(slug)
                except (HTTPError, OSError, UnicodeError, ValueError):
                    # A 404/ChannelNotFoundError can be a transient YouTube-side
                    # hiccup, and some talents' hololivepro profile page no
                    # longer scrapes a channel link (e.g. after graduation) so
                    # this retry can fail every single cycle. Keep last-known
                    # state instead of escalating to "error" and re-logging the
                    # same failure on every refresh forever.
                    return
                channel_urls[name] = target
                for index, (target_name, slug, _, unit) in enumerate(targets):
                    if target_name == name:
                        targets[index] = (target_name, slug, target, unit)
                        break
                try:
                    # attempts=1: this is already the retry after a resolve
                    # + fetch round-trip, so skip fetch_live_info()'s own
                    # internal retry-on-transient-error loop here rather than
                    # letting this one talent's worker thread hold one of
                    # refresh_worker()'s 12 concurrent slots for yet another
                    # full retry cycle on top of everything already tried.
                    video_id, title = youtube.fetch_live_info(target, attempts=1)
                except (HTTPError, youtube.ChannelNotFoundError) as error:
                    if not youtube.is_stale_channel_error(error):
                        raise
                    # Same reasoning as the resolve_channel_url failure just
                    # above: a freshly re-resolved channel that still
                    # 404s/doesn't exist gets the same "keep last-known state,
                    # don't escalate to a logged error every cycle" treatment
                    # rather than falling through to the outer except below.
                    return
            if video_id:
                # Set live_urls before states: open_target() reads states
                # first, so this ordering keeps it from ever observing
                # state == "live" with live_urls not yet populated.
                live_urls[name] = f"https://www.youtube.com/watch?v={video_id}"
                if title:
                    # Strip VARIATION SELECTOR-15 (text-presentation): some
                    # titles pair it with a dingbat/symbol (e.g. "✧︎")
                    # to force plain-text rendering, but Yu Gothic has no glyph
                    # for the selector itself and renders it as a tofu box.
                    # ️ (emoji-presentation) is left alone since that half
                    # of the run already renders fine via the Segoe UI Emoji
                    # fallback in _emoji_runs(). _UNSUPPORTED_DECORATION_RE
                    # strips other known no-glyph decoration the same way.
                    live_titles[name] = _UNSUPPORTED_DECORATION_RE.sub(
                        "", title.replace("︎", ""))
                else:
                    live_titles.pop(name, None)
                states[name] = "live"
            else:
                live_urls.pop(name, None)
                live_titles.pop(name, None)
                states[name] = "offline"
        except (HTTPError, OSError, UnicodeError, ValueError,
                youtube.ChannelNotFoundError) as error:
            states[name] = "error"
            live_urls.pop(name, None)
            live_titles.pop(name, None)
            log_error(name, error)
