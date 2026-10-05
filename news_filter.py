import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List
import config

logger = logging.getLogger("NewsFilter")

class EconomicNewsFilter:
    """
    Monitors economic calendars (ForexFactory feed) for High-Impact events
    and enforces pre/post news trading blackout periods.
    """

    FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    CACHE_FILE = "news_calendar_cache.json"

    def __init__(self, pre_buffer_mins: int = 30, post_buffer_mins: int = 30):
        self.pre_buffer = timedelta(minutes=pre_buffer_mins)
        self.post_buffer = timedelta(minutes=post_buffer_mins)
        self.cached_events: List[Dict[str, Any]] = []
        self.last_fetch_time: Optional[datetime] = None
        self.cache_duration = timedelta(hours=3)
        self._is_fetching = False
        self.load_disk_cache()

    def fetch_calendar_async(self):
        """Spawns non-blocking background thread to refresh economic calendar without stalling trade execution."""
        if getattr(self, "_is_fetching", False):
            return
        self._is_fetching = True
        import threading
        t = threading.Thread(target=self._fetch_calendar_worker, daemon=True, name="NewsFetchWorker")
        t.start()

    def _fetch_calendar_worker(self):
        try:
            self.fetch_calendar()
        finally:
            self._is_fetching = False

    def load_disk_cache(self):
        """Loads events from local disk cache if available."""
        import os, json
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, "r") as f:
                    raw = json.load(f)
                    events = []
                    for ev in raw:
                        events.append({
                            "title": ev.get("title", ""),
                            "country": ev.get("country", "").upper(),
                            "datetime_utc": datetime.fromisoformat(ev["datetime_utc"]),
                            "forecast": ev.get("forecast", ""),
                            "previous": ev.get("previous", "")
                        })
                    self.cached_events = events
                    self.last_fetch_time = datetime.now(timezone.utc)
                    logger.info(f"Loaded {len(self.cached_events)} events from disk cache.")
            except Exception:
                pass

    def save_disk_cache(self):
        """Saves parsed events to local disk cache."""
        import json
        try:
            serialized = []
            for ev in self.cached_events:
                serialized.append({
                    "title": ev["title"],
                    "country": ev["country"],
                    "datetime_utc": ev["datetime_utc"].isoformat(),
                    "forecast": ev["forecast"],
                    "previous": ev["previous"]
                })
            with open(self.CACHE_FILE, "w") as f:
                json.dump(serialized, f)
        except Exception:
            pass

    def extract_currencies(self, symbol: str) -> List[str]:
        """Extracts 3-letter currency codes from a trading symbol (e.g. EURUSDm -> EUR, USD)."""
        clean = symbol.upper().rstrip("M").rstrip("C")
        if len(clean) >= 6:
            return [clean[:3], clean[3:6]]
        return ["USD", "EUR"]

    def fetch_calendar(self) -> bool:
        """Fetches and parses high-impact economic news with rate-limit protection."""
        now = datetime.now(timezone.utc)
        if self.last_fetch_time and (now - self.last_fetch_time) < self.cache_duration:
            return len(self.cached_events) > 0

        # Set last fetch time immediately to prevent 3-second rapid spam on 429
        self.last_fetch_time = now

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            logger.info("Fetching weekly economic calendar from ForexFactory feed...")
            res = requests.get(self.FEED_URL, headers=headers, timeout=8)
            if res.status_code == 200:
                raw_events = res.json()
                high_impact = []
                for ev in raw_events:
                    if ev.get("impact") == "High":
                        try:
                            ev_time = datetime.fromisoformat(ev["date"])
                            ev_time_utc = ev_time.astimezone(timezone.utc)
                            high_impact.append({
                                "title": ev.get("title", ""),
                                "country": ev.get("country", "").upper(),
                                "datetime_utc": ev_time_utc,
                                "forecast": ev.get("forecast", ""),
                                "previous": ev.get("previous", "")
                            })
                        except Exception:
                            continue
                self.cached_events = high_impact
                self.save_disk_cache()
                logger.info(f"Loaded {len(self.cached_events)} high-impact economic events.")
                return True
            else:
                logger.warning(f"ForexFactory calendar returned HTTP {res.status_code}. Using cached events ({len(self.cached_events)}).")
                # Back off for 30 minutes on rate limit
                self.last_fetch_time = now - self.cache_duration + timedelta(minutes=30)
                return len(self.cached_events) > 0
        except Exception as e:
            logger.warning(f"News calendar fetch failed: {e}. Using cached events ({len(self.cached_events)}).")
            return len(self.cached_events) > 0

    def is_news_blackout(self, symbol: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Checks if current time is within blackout window of any high-impact event for the symbol's currencies.
        Returns (is_blackout, reason_str, active_event_dict).
        """
        if not config.NEWS_FILTER_ENABLED:
            return False, "News filter disabled", None

        now_utc = datetime.now(timezone.utc)
        if not self.last_fetch_time or (now_utc - self.last_fetch_time) >= self.cache_duration:
            self.fetch_calendar_async()

        if not self.cached_events:
            return False, "No active news events loaded", None

        now_utc = datetime.now(timezone.utc)
        currencies = self.extract_currencies(symbol)

        for ev in self.cached_events:
            if ev["country"] in currencies or ev["country"] == "ALL":
                ev_time = ev["datetime_utc"]
                start_window = ev_time - self.pre_buffer
                end_window = ev_time + self.post_buffer

                if start_window <= now_utc <= end_window:
                    mins_diff = int((ev_time - now_utc).total_seconds() / 60)
                    if mins_diff > 0:
                        reason = f"High-impact news '{ev['title']}' ({ev['country']}) in {mins_diff} mins. Trading paused."
                    else:
                        reason = f"High-impact news '{ev['title']}' ({ev['country']}) passed {abs(mins_diff)} mins ago. Waiting for post-event volatility to settle."
                    return True, reason, ev

        return False, "No imminent high-impact news", None
