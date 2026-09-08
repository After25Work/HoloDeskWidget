"""Background refresh machinery: kicking off per-talent worker threads,
resolving/caching each talent's channel URL, and fetching live status from
YouTube. Runs off the Tk main thread (see refresh_worker()'s note), only ever
touching self.production_data[prod_id] directly rather than the
active-tab-relative self.targets/self.states/etc. properties.
"""
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from urllib.error import HTTPError

from . import stream_log, youtube
from .paths import log_error
from .talents import ALL_PRODUCTION_ID, UNOBSERVED_STATE

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

# Re-opening the same target link within this window of the last open is
# treated as a duplicate click rather than two intentional opens.
REOPEN_DEBOUNCE_SECONDS = 0.5
# Only this many talent checks run concurrently at once, even when a
# refresh cycle queues hundreds of tasks (the "All" tab across every
# production) -- see refresh_worker()'s own note on why a fixed-size pool
# drains a queue instead of one thread per talent.
MAX_REFRESH_WORKERS = 12
# How often refresh_complete() reschedules the next automatic refresh.
REFRESH_INTERVAL_MS = 60_000


class RefreshMixin:
    def open_target(self, target):
        name, _, url, _ = target
        now = time.monotonic()
        if self.last_opened[0] == name and now - self.last_opened[1] < REOPEN_DEBOUNCE_SECONDS:
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
                jobs = [(production["id"], self.production_data[production["id"]], production.get("auto_resolve"))
                        for production in self._visible_productions()]
            else:
                jobs = [(prod_id, self.production_data[prod_id], self._productions_by_id[prod_id].get("auto_resolve"))]
            tasks = [(job_prod_id, slot, auto_resolve, name, slug, target)
                     for job_prod_id, slot, auto_resolve in jobs
                     for name, slug, target, _ in slot["targets"]]
            if not tasks:
                return
            task_queue = queue.Queue()
            for task in tasks:
                task_queue.put(task)

            def drain_queue():
                while True:
                    try:
                        task = task_queue.get_nowait()
                    except queue.Empty:
                        return
                    self.check_one(*task)

            # A small fixed-size pool draining a queue, not one thread per
            # talent: on the "All" tab across every production (hundreds of
            # talents for the VT variant) a thread-per-talent approach spawns
            # and tears down hundreds of OS threads every single refresh
            # cycle even though only 12 of them ever do real work at once.
            # Still plain daemon threads rather than ThreadPoolExecutor: its
            # worker threads register with concurrent.futures' own atexit
            # hook and get joined before the interpreter is allowed to exit,
            # so a single slow/hanging youtube.fetch_live_info() call — which
            # can stack multiple 20s-timeout network requests (channel-id
            # resolution, an internal retry on the browse call, and this
            # module's own 404 channel re-resolve path) well past a single
            # 20s bound — would keep the whole process — and the
            # single-instance mutex it holds — alive well after the window
            # closes. Daemon threads are simply abandoned on exit instead.
            pool_size = min(MAX_REFRESH_WORKERS, len(tasks))
            workers = [threading.Thread(target=drain_queue, daemon=True) for _ in range(pool_size)]
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
        if self.tray is not None:
            self.tray.update_tooltip(self._tray_tooltip_text())
        if prod_id == self.active_production:
            self.last_updated = time.strftime("%H:%M:%S")
            self.render()
            self.root.after(REFRESH_INTERVAL_MS, self.refresh)
        else:
            # The user switched tabs while this (now-stale) production's
            # refresh was still in flight — kick an immediate refresh for
            # whatever's active now instead of waiting out this one's 60s
            # cycle. That refresh's own refresh_complete() schedules the
            # next periodic tick, so this doesn't create a second loop.
            self.refresh()

    @staticmethod
    def _resolve_channel_url(slot, auto_resolve, name, slug, target):
        """Ensures slot['channel_urls'][name] is populated and returns it.
        `auto_resolve` is the owning production's manifest field: only
        "hololivepro" scrapes hololive's official talent pages for a
        channel URL; every other production (including custom) uses
        `target` (channel_url from its JSON) as-is and never attempts a
        hololive-site re-resolve."""
        channel_urls = slot["channel_urls"]
        if name not in channel_urls:
            if auto_resolve == "hololivepro":
                try:
                    resolved = youtube.resolve_channel_url(slug)
                except (HTTPError, OSError, UnicodeError, ValueError):
                    resolved = target
            else:
                resolved = target
            # Guards against _merge_all_slots() reading/merging this dict on
            # the Tk main thread at the same time (see the note by "lock" in
            # _production_slot()).
            with slot["lock"]:
                channel_urls[name] = resolved
        return channel_urls[name]

    @staticmethod
    def _fetch_with_stale_retry(slot, auto_resolve, name, slug, target):
        """Fetches live info for `target`, re-resolving and retrying once on
        a stale-channel error (see youtube.is_stale_channel_error). Returns
        (video_id, title) on success, or None if the retry itself hit a
        stale-channel error or the re-resolve failed -- both of which mean
        "keep last-known state, don't escalate to a logged error every
        cycle" to the caller. Propagates any other exception."""
        try:
            return youtube.fetch_live_info(target)
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
                # this retry can fail every single cycle.
                return None
            targets, channel_urls = slot["targets"], slot["channel_urls"]
            with slot["lock"]:
                channel_urls[name] = target
                for index, (target_name, target_slug, _, unit) in enumerate(targets):
                    if target_name == name:
                        targets[index] = (target_name, target_slug, target, unit)
                        break
            try:
                # attempts=1: this is already the retry after a resolve
                # + fetch round-trip, so skip fetch_live_info()'s own
                # internal retry-on-transient-error loop here rather than
                # letting this one talent's worker thread hold one of
                # refresh_worker()'s MAX_REFRESH_WORKERS concurrent slots for
                # yet another full retry cycle on top of everything already
                # tried.
                return youtube.fetch_live_info(target, attempts=1)
            except (HTTPError, youtube.ChannelNotFoundError) as error:
                if not youtube.is_stale_channel_error(error):
                    raise
                # Same reasoning as the resolve_channel_url failure just
                # above: a freshly re-resolved channel that still
                # 404s/doesn't exist gets the same "keep last-known state"
                # treatment rather than falling through to the outer except.
                return None

    @staticmethod
    def _clear_live_state(slot, name, state):
        with slot["lock"]:
            slot["live_urls"].pop(name, None)
            slot["live_titles"].pop(name, None)
            slot["states"][name] = state

    def check_one(self, prod_id, slot, auto_resolve, name, slug, target):
        # Operates on the explicit `slot` dict (self.production_data[prod_id])
        # rather than the self.targets/self.states/etc. properties, which
        # always reflect whichever production is active_production *right
        # now* — see the note above those properties.
        states, live_urls, live_titles = slot["states"], slot["live_urls"], slot["live_titles"]
        lock = slot["lock"]
        # Snapshotted once up front: check_one() only ever lands on one of the
        # states[name] = ... assignments below per call, so this alone is
        # enough to tell a real start/end transition (see
        # _log_state_transition()) from a refresh that just reconfirms the
        # same state as before.
        previous_state = states.get(name)
        try:
            target = self._resolve_channel_url(slot, auto_resolve, name, slug, target)
            result = self._fetch_with_stale_retry(slot, auto_resolve, name, slug, target)
            if result is None:
                return
            video_id, title = result
            if video_id:
                # Set live_urls before states: open_target() reads states
                # first, so this ordering keeps it from ever observing
                # state == "live" with live_urls not yet populated.
                with lock:
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
                self._log_state_transition(prod_id, name, previous_state, "live",
                                            live_titles.get(name), live_urls.get(name))
            else:
                self._clear_live_state(slot, name, "offline")
                self._log_state_transition(prod_id, name, previous_state, "offline")
        except (HTTPError, OSError, UnicodeError, ValueError,
                youtube.ChannelNotFoundError) as error:
            self._clear_live_state(slot, name, "error")
            log_error(name, error)
            self._log_state_transition(prod_id, name, previous_state, "error")

    @staticmethod
    def _log_state_transition(prod_id, name, previous_state, new_state, title=None, url=None):
        # Only a transition into "live" or a *confirmed* drop out of it is a
        # meaningful stream boundary. new_state == "error" means the fetch
        # itself failed (a transient network hiccup, most likely) -- it says
        # nothing about whether the stream actually ended, so treating it as
        # an "end" here would log a false end+restart pair around every
        # ordinary blip on a channel that's still live. offline<->error
        # churn (a talent with no scheduled stream hitting an occasional
        # fetch error) is noise the history viewer has no use for either way.
        # UNOBSERVED_STATE is _production_slot()'s seed value for every
        # talent at the start of each app session (never a real observed
        # state) -- excluding it here keeps a restart while someone is
        # already live from logging a false "start" for a stream that's
        # actually been running since before this session began.
        if new_state == "live" and previous_state not in ("live", UNOBSERVED_STATE):
            stream_log.record_event(prod_id, name, "start", title, url)
        elif new_state == "offline" and previous_state == "live":
            stream_log.record_event(prod_id, name, "end")
