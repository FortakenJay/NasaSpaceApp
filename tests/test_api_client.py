"""The central external-API client: every optimisation that keeps the number of NASA requests small."""
import json
import threading
import time

import pytest

from marswalk.sources import api_client
from marswalk.sources.api_client import ApiClient, RateLimited

URL = "https://api.nasa.gov/DONKI/SEP?startDate=2026-11-07&endDate=2026-11-14&api_key=SECRETKEY123"
MIRROR = "https://mirror.example/DONKI/SEP?startDate=2026-11-07&endDate=2026-11-14"


class Nasa:
    """A fake transport that counts calls and can be told to fail."""

    def __init__(self, data=None):
        self.calls, self.fail, self.headers, self.data, self.delay = [], None, {}, data if data is not None else [{"n": 1}], 0.0

    def __call__(self, url, timeout=0):
        self.calls.append(url)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return json.dumps(self.data), dict(self.headers)


def test_answers_are_cached_per_feed_in_memory_and_on_disk(tmp_path):
    nasa = Nasa()
    c = ApiClient(tmp_path, nasa)
    assert c.get_json("sep", URL).state == "fresh"
    again = c.get_json("sep", URL)
    assert again.state == "cached" and again.data == [{"n": 1}] and len(nasa.calls) == 1
    restarted = ApiClient(tmp_path, nasa)                         # a restart reads the disk copy
    assert restarted.get_json("sep", URL).state == "cached" and len(nasa.calls) == 1
    assert c.stats["requests_sent"] == 1 and c.stats["served_from_cache"] == 1


def test_stale_copy_is_used_when_nasa_does_not_answer_and_failures_back_off(tmp_path):
    nasa = Nasa()
    c = ApiClient(tmp_path, nasa)
    c.get_json("sep", URL)
    nasa.fail = OSError("timed out")
    r = c.get_json("sep", URL, ttl_s=0)                           # the copy has expired and NASA is down
    assert r.state == "stale" and r.data == [{"n": 1}] and "timed out" in r.error and len(nasa.calls) == 2
    r = c.get_json("sep", URL, ttl_s=0)                           # backing off: NASA is not asked again
    assert r.state == "stale" and "waiting" in r.error and len(nasa.calls) == 2 and c.stats["skipped_backing_off"] == 1
    nasa.fail = None
    assert c.get_json("sep", URL, ttl_s=0, force=True).state == "fresh" and len(nasa.calls) == 3   # the button overrides
    assert c.get_json("flr", URL.replace("SEP", "FLR"), stale_s=0).state == "fresh"


def test_nothing_saved_and_no_answer_is_missing(tmp_path):
    nasa = Nasa()
    nasa.fail = OSError("no route")
    r = ApiClient(tmp_path, nasa).get_json("sep", URL)
    assert r.state == "missing" and r.data is None and not r.ok


def test_mirror_is_tried_and_rate_limits_are_respected(tmp_path):
    seen = []

    def transport(url, timeout=0):
        seen.append(url)
        if "api.nasa.gov" in url:
            raise RateLimited("HTTP 429 (request limit reached)", 120)
        return "[]", {}
    c = ApiClient(tmp_path, transport)
    r = c.get_json("sep", [URL, MIRROR])
    assert r.state == "fresh" and r.data == [] and seen == [URL, MIRROR] and c.rate["remaining"] == 0

    nasa = Nasa()
    nasa.headers = {"x-ratelimit-limit": "30", "x-ratelimit-remaining": "3"}
    c = ApiClient(tmp_path / "b", nasa)
    c.get_json("sep", URL)
    r = c.get_json("sep", URL, ttl_s=0)                           # 3 requests left: keep them, reuse the copy
    assert r.state == "stale" and "reserve" in r.error and len(nasa.calls) == 1 and c.stats["skipped_low_budget"] == 1


def test_the_key_never_reaches_cache_files_errors_or_the_snapshot(tmp_path):
    def transport(url, timeout=0):
        raise OSError(f"could not open {url}")
    c = ApiClient(tmp_path, transport)
    r = c.get_json("sep", URL)
    assert "SECRETKEY123" not in r.error and "api_key=***" in r.error
    ok = ApiClient(tmp_path / "ok", Nasa())
    ok.get_json("sep", URL)
    text = "".join(p.read_text() for p in (tmp_path / "ok").glob("*.json")) + json.dumps(ok.snapshot()) + json.dumps(c.snapshot())
    assert "SECRETKEY123" not in text and "sep" in text


def test_get_many_answers_at_the_deadline_and_slow_feeds_finish_in_the_background(tmp_path):
    slow, fast = Nasa([{"slow": True}]), Nasa([{"fast": True}])
    slow.delay = 0.4

    def transport(url, timeout=0):
        return (slow if "FLR" in url else fast)(url, timeout)
    c = ApiClient(tmp_path, transport)
    reqs = {"sep": {"urls": URL}, "flr": {"urls": URL.replace("SEP", "FLR")}}
    t = time.monotonic()
    got = c.get_many(reqs, deadline_s=0.1)
    assert time.monotonic() - t < 0.35
    assert got["sep"].state == "fresh" and got["flr"].state == "missing" and "still waiting" in got["flr"].error
    # asked again while the slow request is still running: no second request, no waiting
    assert c.get_many(reqs, deadline_s=0.1)["flr"].state == "missing" and len(slow.calls) == 1
    time.sleep(0.6)
    got = c.get_many(reqs, deadline_s=0.1)                        # the slow answer arrived meanwhile
    assert got["flr"].state == "cached" and got["flr"].data == [{"slow": True}] and len(slow.calls) == 1
    assert {f["name"] for f in c.snapshot()["feeds"]} == {"sep", "flr"}


def test_concurrent_callers_share_one_request(tmp_path):
    nasa = Nasa()
    nasa.delay = 0.15
    c = ApiClient(tmp_path, nasa)
    threads = [threading.Thread(target=c.get_json, args=("sep", URL)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(nasa.calls) == 1 and c.stats["served_from_cache"] == 4


def test_real_transport_is_off_in_tests():
    with pytest.raises(OSError):
        api_client.http_get(URL)
