"""The one place MarsWalk talks to external web APIs (today: NASA DONKI through api.nasa.gov).

Nothing else in the package opens an HTTP connection to an API. Routing every request through ApiClient is what
keeps the number of requests small and the app responsive when NASA is slow:

  1. Cache with a time-to-live per feed, in memory and on disk (data/cache/api/), so restarts cost nothing.
  2. Each feed is cached on its own: one slow feed never forces the others to be asked again.
  3. Stale-if-error: when NASA does not answer, the last good copy (up to `stale_s` old) is used and labelled.
  4. Stale-while-revalidate: get_many() returns at its deadline with what it has; requests still running finish
     in the background and fill the cache for the next call.
  5. Back-off after failures (1 min, doubling to 10 min) and after HTTP 429, so a struggling feed is not hammered
     and the page does not wait on it again and again.
  6. One request per feed at a time: concurrent callers wait for the first answer instead of asking twice.
  7. Request budget: X-RateLimit-* headers are tracked; when few requests are left, cached copies are preferred.
  8. Mirrors: a feed can list several URLs (api.nasa.gov, then the keyless CCMC mirror).
  9. Transport that survives common network quirks: IPv4 first (Python otherwise waits on dead IPv6 routes),
     then the system `curl`.
 10. Keys never reach logs, cache files or error messages (the api_key value is redacted).

snapshot() reports all of this for GET /api/sources, which the app shows under "NASA data connections".
"""
from __future__ import annotations

import collections
import hashlib
import http.client
import json
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

USER_AGENT = "marswalk/0.7 (research prototype)"
LOW_BUDGET = 5                 # below this many remaining requests, cached copies are preferred over asking
BACKOFF_START_S, BACKOFF_MAX_S = 60.0, 600.0
_KEY_RE = re.compile(r"(api_key=)[^&\s]+")


def redact(text: str) -> str:
    return _KEY_RE.sub(r"\1***", text)


def plain_error(error: str) -> str:
    """A raw transport error ("python: timed out; curl: (28) ...") as one sentence a user can act on."""
    e = (error or "").lower()
    if not e:
        return ""
    if "waiting" in e and "before asking again" in e:
        return "It failed a moment ago, so MarsWalk is waiting before asking again."
    if "requests left" in e:
        return "Few NASA requests are left this hour, so MarsWalk is reusing its saved copy."
    if "429" in e or "rate limit" in e or "too many requests" in e:
        return "NASA's request limit for this key was reached. A personal key in .env raises it."
    if "timed out" in e or "timeout" in e:
        return "NASA's server did not answer in time. It is often slow; MarsWalk keeps trying in the background."
    if any(k in e for k in ("name or service", "nodename", "resolve", "unreachable", "no route", "refused")):
        return "This computer could not reach NASA's server. Check the internet connection."
    if "403" in e or "401" in e:
        return "NASA refused the request. Check NASA_API_KEY in .env."
    if any(k in e for k in ("500", "502", "503", "504")):
        return "NASA's server had an error. MarsWalk will ask again later."
    if "expecting value" in e or "json" in e:
        return "NASA's server sent an answer MarsWalk could not read."
    return "NASA's server did not give a usable answer."


# ---------------------------------------------------------------- transport
def _connect_ipv4(address, timeout=None, source_address=None):
    """socket.create_connection, but IPv4 only. Python tries IPv6 first and, unlike a browser, waits out the
    whole timeout on networks where IPv6 is advertised but does not route."""
    host, port = address
    last: Exception | None = None
    for *_, sockaddr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if isinstance(timeout, (int, float)):
                sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            last = e
            sock.close()
    raise last or OSError(f"no IPv4 address for {host}")


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_ipv4


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=ssl.create_default_context())


class RateLimited(OSError):
    """HTTP 429. `retry_after_s` is the server's hint, if it gave one."""

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


def http_get(url: str, timeout: float = 8.0) -> tuple[str, dict]:
    """GET a URL. Returns (text, lower-cased headers). Python over IPv4 first, then the system `curl`."""
    errors = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.build_opener(_IPv4HTTPSHandler()).open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = e.headers.get("Retry-After") if e.headers else None
            raise RateLimited("HTTP 429 (request limit reached)", float(retry) if retry and retry.isdigit() else None) from e
        errors.append(f"HTTP {e.code}")
    except (OSError, ValueError) as e:          # URLError, timeouts and SSL errors are OSError
        errors.append(f"python: {getattr(e, 'reason', e)}")
    curl = shutil.which("curl")
    if curl:
        try:
            done = subprocess.run([curl, "-sS", "-f", "-L", "--max-time", str(int(timeout)), "-A", USER_AGENT, url],
                                  capture_output=True, text=True, timeout=timeout + 2)
            if done.returncode == 0:
                return done.stdout, {}
            errors.append(f"curl: {done.stderr.strip()[:100]}")
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"curl: {e}")
    raise OSError(redact("; ".join(errors)))


# ---------------------------------------------------------------- client
@dataclass
class Fetched:
    data: object | None
    state: str                    # "fresh" (just asked) | "cached" (within its TTL) | "stale" (old copy, NASA did not answer) | "missing"
    fetched_at: float | None      # epoch seconds of the copy in `data`
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.data is not None


Transport = Callable[[str, float], tuple[str, dict]]


class ApiClient:
    def __init__(self, cache_dir: Path | None = None, transport: Transport | None = None):
        self.cache_dir = cache_dir
        self.transport = transport        # None = this module's http_get, looked up at call time
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._mem: dict[str, tuple[float, object]] = {}
        self._fail: dict[str, tuple[int, float, str]] = {}       # key -> (failures in a row, retry-after epoch, error)
        self._feeds: dict[str, dict] = {}                        # name -> last outcome, for snapshot()
        self.stats = collections.Counter()
        self.rate: dict[str, int | None] = {"limit": None, "remaining": None}

    # -- cache -------------------------------------------------------------------------------------
    @staticmethod
    def _key(name: str, urls: list[str]) -> str:
        return f"{name}-{hashlib.sha1(redact(urls[0]).encode()).hexdigest()[:12]}"

    def _path(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    def _load(self, key: str) -> tuple[float, object] | None:
        if key in self._mem:
            return self._mem[key]
        p = self._path(key)
        if p and p.exists():
            try:
                raw = json.loads(p.read_text())
                self._mem[key] = (float(raw["fetched_at"]), raw["data"])
                return self._mem[key]
            except (ValueError, KeyError, TypeError, OSError):
                return None
        return None

    def _store(self, key: str, url: str, data: object) -> float:
        now = time.time()
        self._mem[key] = (now, data)
        p = self._path(key)
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"fetched_at": now, "url": redact(url), "data": data}))
        return now

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def _note(self, name: str, result: Fetched, ttl_s: float) -> Fetched:
        with self._guard:
            retry = self._fail.get(name + ":retry")
            self._feeds[name] = {"name": name, "state": result.state, "fetched_at": result.fetched_at, "ttl_s": ttl_s,
                                 "error": result.error, "retry_at": retry[1] if retry else None}
        return result

    # -- requests ----------------------------------------------------------------------------------
    def get_json(self, name: str, urls: list[str] | str, *, ttl_s: float = 1800.0, timeout_s: float = 8.0,
                 stale_s: float = 86400.0, force: bool = False) -> Fetched:
        """JSON from the first URL that answers, through the cache. Never raises on network trouble."""
        urls = [urls] if isinstance(urls, str) else list(urls)
        key = self._key(name, urls)
        with self._lock(key):                                    # one request per feed at a time
            now = time.time()
            entry = self._load(key)
            if entry and not force and now - entry[0] < ttl_s:
                self.stats["served_from_cache"] += 1
                return self._note(name, Fetched(entry[1], "cached", entry[0]), ttl_s)

            def fallback(error: str) -> Fetched:
                if entry and now - entry[0] < stale_s:
                    self.stats["served_stale"] += 1
                    return self._note(name, Fetched(entry[1], "stale", entry[0], error), ttl_s)
                return self._note(name, Fetched(None, "missing", None, error), ttl_s)

            fail = self._fail.get(key)
            if fail and now < fail[1] and not force:
                self.stats["skipped_backing_off"] += 1
                return fallback(f"{fail[2]} (waiting {int(fail[1] - now)} s before asking again)")
            remaining = self.rate["remaining"]
            if entry and remaining is not None and remaining <= LOW_BUDGET and not force:
                self.stats["skipped_low_budget"] += 1
                return fallback(f"only {remaining} requests left this hour, keeping them in reserve")

            error, backoff = "", None
            for url in urls:
                try:
                    self.stats["requests_sent"] += 1
                    text, headers = (self.transport or http_get)(url, timeout_s)
                    data = json.loads(text) if text.strip() else []       # DONKI answers an empty body for "nothing"
                    for field in ("limit", "remaining"):
                        v = headers.get(f"x-ratelimit-{field}")
                        if v and v.isdigit():
                            self.rate[field] = int(v)
                    self._fail.pop(key, None)
                    self._fail.pop(name + ":retry", None)
                    return self._note(name, Fetched(data, "fresh", self._store(key, url, data)), ttl_s)
                except RateLimited as e:
                    self.rate["remaining"] = 0
                    error, backoff = str(e), e.retry_after_s or 900.0
                except (OSError, ValueError) as e:
                    error = redact(str(e))[:200]
            self.stats["failed"] += 1
            count = (fail[0] if fail else 0) + 1
            wait = backoff or min(BACKOFF_START_S * 2 ** (count - 1), BACKOFF_MAX_S)
            self._fail[key] = (count, time.time() + wait, error)
            self._fail[name + ":retry"] = (count, time.time() + wait, error)
            return fallback(error)

    def get_many(self, requests: dict[str, dict], deadline_s: float = 12.0, force: bool = False) -> dict[str, Fetched]:
        """Ask several feeds at once. Returns at the deadline with what has arrived; slower requests keep
        running in the background and land in the cache for the next call.

        requests: name -> {"urls": [...], "ttl_s": ..., "timeout_s": ..., "stale_s": ...}
        """
        slow = "still waiting for NASA (slow feed); the answer will be used as soon as it arrives"
        out: dict[str, Fetched] = {}

        def without_waiting(name: str, kw: dict, error: str) -> Fetched:
            urls = [kw["urls"]] if isinstance(kw["urls"], str) else kw["urls"]
            entry = self._load(self._key(name, urls))
            if entry and time.time() - entry[0] < kw.get("ttl_s", 1800.0):
                return self._note(name, Fetched(entry[1], "cached", entry[0]), kw.get("ttl_s", 1800.0))
            if entry and time.time() - entry[0] < kw.get("stale_s", 86400.0):
                self.stats["served_stale"] += 1
                return self._note(name, Fetched(entry[1], "stale", entry[0], error), kw.get("ttl_s", 1800.0))
            return self._note(name, Fetched(None, "missing", None, error), kw.get("ttl_s", 1800.0))

        todo = {}
        for name, kw in requests.items():
            urls = [kw["urls"]] if isinstance(kw["urls"], str) else kw["urls"]
            if self._lock(self._key(name, urls)).locked():        # an earlier request for this feed is still running
                out[name] = without_waiting(name, kw, slow)
            else:
                todo[name] = kw
        pool = ThreadPoolExecutor(max_workers=max(len(todo), 1), thread_name_prefix="marswalk-api")
        jobs = {name: pool.submit(self.get_json, name, force=force, **kw) for name, kw in todo.items()}
        end = time.monotonic() + deadline_s
        for name, job in jobs.items():
            try:
                out[name] = job.result(timeout=max(end - time.monotonic(), 0.05))
            except Exception as e:  # noqa: BLE001 - includes the deadline (TimeoutError)
                out[name] = without_waiting(name, todo[name], slow if isinstance(e, TimeoutError) else redact(str(e))[:200])
        pool.shutdown(wait=False)
        return out

    def snapshot(self) -> dict:
        now = time.time()
        with self._guard:
            feeds = [{"name": f["name"], "state": f["state"], "error": f["error"], "problem": plain_error(f["error"]),
                      "age_s": None if f["fetched_at"] is None else round(now - f["fetched_at"]),
                      "fresh_for_s": None if f["fetched_at"] is None else max(round(f["ttl_s"] - (now - f["fetched_at"])), 0),
                      "retry_in_s": None if not f["retry_at"] or f["retry_at"] < now else round(f["retry_at"] - now)}
                     for f in self._feeds.values()]
        return {"feeds": feeds, "stats": {k: self.stats[k] for k in ("requests_sent", "served_from_cache", "served_stale",
                                                                    "skipped_backing_off", "skipped_low_budget", "failed")},
                "rate_limit": dict(self.rate)}


_CLIENTS: dict[str, ApiClient] = {}


def get_client(cache_dir: Path | None = None) -> ApiClient:
    """Process-wide client for a cache folder (one per folder, so tests with their own data dir stay isolated)."""
    key = str(cache_dir)
    if key not in _CLIENTS:
        _CLIENTS[key] = ApiClient(cache_dir)
    return _CLIENTS[key]
