"""Polite HTTP client: one request at a time, fixed delay, robots.txt, 429 back-off, time budget."""
from __future__ import annotations

import random
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin

import requests


class RateLimited(Exception):
    """The site keeps answering 429; stop for this run and resume next time."""


class OutOfTime(Exception):
    """The run's time budget is used up; progress is saved and the next run resumes."""


@dataclass
class Response:
    url: str
    status: int
    text: str


class PoliteClient:
    def __init__(self, http_cfg: dict, deadline: float):
        self.base = http_cfg["base_url"].rstrip("/")
        self.delay = float(http_cfg["delay_seconds"])
        self.jitter = float(http_cfg.get("jitter_seconds", 0))
        self.timeout = float(http_cfg["timeout_seconds"])
        self.max_retries = int(http_cfg["max_retries"])
        self.max_429 = int(http_cfg["max_consecutive_429"])
        self.deadline = deadline
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": http_cfg["user_agent"],
            "Accept-Language": "de,en;q=0.8",
        })
        self._last = 0.0
        self._consecutive_429 = 0
        self.requests_made = 0
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_loaded = False

    # -- helpers ---------------------------------------------------------
    def abs_url(self, path_or_url: str) -> str:
        return urljoin(self.base + "/", path_or_url)

    def time_left(self) -> float:
        return self.deadline - time.time()

    def _load_robots(self) -> None:
        if self._robots_loaded:
            return
        try:
            r = self.session.get(self.base + "/robots.txt", timeout=self.timeout)
            self._robots.parse(r.text.splitlines() if r.ok else [])
        except requests.RequestException:
            self._robots.parse([])
        self._robots_loaded = True

    def _wait_turn(self) -> None:
        gap = self.delay + random.uniform(0, self.jitter)
        sleep_for = self._last + gap - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)

    # -- main entry ------------------------------------------------------
    def get(self, path_or_url: str) -> Response:
        url = self.abs_url(path_or_url)
        self._load_robots()
        ua = self.session.headers["User-Agent"]
        if not self._robots.can_fetch(ua, url):
            return Response(url, 999, "")  # disallowed by robots.txt; never fetched

        backoff = 60.0
        for attempt in range(self.max_retries + 1):
            if self.time_left() < 30:
                raise OutOfTime()
            self._wait_turn()
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException:
                self._last = time.time()
                time.sleep(min(backoff, 30))
                continue
            self._last = time.time()
            self.requests_made += 1

            if r.status_code == 429 or r.status_code == 503:
                self._consecutive_429 += 1
                if self._consecutive_429 >= self.max_429:
                    raise RateLimited(f"{self._consecutive_429} rate-limit answers in a row")
                retry_after = r.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else backoff
                print(f"  [429] waiting {wait:.0f}s before retrying {url}")
                time.sleep(min(wait, max(self.time_left() - 30, 0)))
                backoff = min(backoff * 2, 900)
                continue

            self._consecutive_429 = 0
            if r.status_code >= 500:
                time.sleep(min(backoff, 60))
                continue
            r.encoding = r.encoding or "utf-8"
            return Response(r.url, r.status_code, r.text)

        return Response(url, 0, "")  # gave up after retries
