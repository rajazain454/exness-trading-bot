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

    def __init__(self, pre_buffer_mins: int = 30, post_buffer_mins: int = 30):
        self.pre_buffer = timedelta(minutes=pre_buffer_mins)
        self.post_buffer = timedelta(minutes=post_buffer_mins)
        self.cached_events: List[Dict[str, Any]] = []
        self.last_fetch_time: Optional[datetime] = None
        self.cache_duration = timedelta(hours=3)

    def extract_currencies(self, symbol: str) -> List[str]:
        """Extracts 3-letter currency codes from a trading symbol (e.g. EURUSDm -> EUR, USD)."""
        clean = symbol.upper().rstrip("M").rstrip("C")
        if len(clean) >= 6:
            return [clean[:3], clean[3:6]]
        return ["USD", "EUR"]

    def fetch_calendar(self) -> bool:
        """Fetches and parses high-impact economic news."""
        now = datetime.now(timezone.utc)
        if self.last_fetch_time and (now - self.last_fetch_time) < self.cache_duration and self.cached_events:
            return True

        try:
            logger.info("Fetching weekly economic calendar from ForexFactory feed...")
            res = requests.get(self.FEED_URL, timeout=8)
            if res.status_code == 200:
                raw_events = res.json()
                high_impact = []
                for ev in raw_events:
                    if ev.get("impact") == "High":
                        try:
                            # Parses ISO 8601 with offset
                            ev_time = datetime.fromisoformat(ev["date"])
                            # Normalize to UTC
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
                self.last_fetch_time = now
                logger.info(f"Loaded {len(self.cached_events)} high-impact economic events.")
                return True
            else:
                logger.warning(f"Could not load news calendar (HTTP {res.status_code}).")
                return False
        except Exception as e:
            logger.warning(f"News calendar fetch failed: {e}. Defaulting to safe state.")
            return False

    def is_news_blackout(self, symbol: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Checks if current time is within blackout window of any high-impact event for the symbol's currencies.
        Returns (is_blackout, reason_str, active_event_dict).
        """
        if not config.NEWS_FILTER_ENABLED:
            return False, "News filter disabled", None

        self.fetch_calendar()
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
