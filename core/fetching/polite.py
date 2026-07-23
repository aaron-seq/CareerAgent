"""
A polite HTTP fetcher for the scraping fallback.

Only used when a target has neither an API nor JSON-LD. It:

* respects ``robots.txt`` (per-host, cached),
* enforces a minimum per-host interval with jitter,
* caches responses in-process,
* backs off on 429/5xx.

Time and sleep are injectable so rate-limiting is unit-testable without real
waits, and the ``httpx.Client`` is injectable so network is mockable.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "CareerAgent/1.0 (+https://github.com/aaron-seq/CareerAgent)"


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL."""


@dataclass
class PoliteFetcher:
    client: Optional[httpx.Client] = None
    min_interval: float = 1.0
    max_retries: int = 3
    user_agent: str = USER_AGENT
    respect_robots: bool = True
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    jitter: Callable[[], float] = lambda: random.uniform(0, 0.3)

    _last_fetch: dict[str, float] = field(default_factory=dict, init=False)
    _robots: dict[str, RobotFileParser] = field(default_factory=dict, init=False)
    _cache: dict[str, httpx.Response] = field(default_factory=dict, init=False)

    def _get_client(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client()
        return self.client

    def _host(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _robots_for(self, url: str) -> RobotFileParser:
        host = self._host(url)
        if host in self._robots:
            return self._robots[host]
        rp = RobotFileParser()
        rp.set_url(f"{host}/robots.txt")
        try:
            resp = self._get_client().get(
                f"{host}/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=10.0,
            )
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])  # no robots => allow all
        except httpx.HTTPError:
            rp.parse([])
        self._robots[host] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        return self._robots_for(url).can_fetch(self.user_agent, url)

    def _respect_rate_limit(self, url: str) -> None:
        host = self._host(url)
        last = self._last_fetch.get(host)
        if last is not None:
            elapsed = self.now() - last
            wait = self.min_interval - elapsed
            if wait > 0:
                self.sleep(wait + self.jitter())
        self._last_fetch[host] = self.now()

    def get(self, url: str, use_cache: bool = True) -> httpx.Response:
        """Fetch a URL politely. Raises :class:`RobotsDisallowed` if blocked."""
        if use_cache and url in self._cache:
            return self._cache[url]
        if not self.can_fetch(url):
            raise RobotsDisallowed(url)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._respect_rate_limit(url)
            resp = self._get_client().get(
                url, headers={"User-Agent": self.user_agent}, timeout=15.0
            )
            if resp.status_code < 400:
                if use_cache:
                    self._cache[url] = resp
                return resp
            if resp.status_code in (429, 500, 502, 503, 504):
                # Exponential backoff before retrying.
                self.sleep(min(2**attempt, 30) + self.jitter())
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
                continue
            resp.raise_for_status()
        if last_exc:
            raise last_exc
        raise httpx.HTTPError(f"Failed to fetch {url}")
