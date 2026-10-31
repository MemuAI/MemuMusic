"""Release date from the GitHub release: parsing, cache, fallback, non-blocking.

No real network anywhere: GitHub answers are faked by mocking
``urllib.request.urlopen``. The pure-logic tests run on the standard
library alone; the server tests are skipped where FastAPI is missing.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memumusic import RELEASE_DATE, __version__, release_date

try:
    import httpx  # noqa: F401
    from fastapi.testclient import TestClient  # noqa: F401
    _HAS_SERVER_DEPS = True
except ImportError:  # pragma: no cover - only on machines without the deps
    _HAS_SERVER_DEPS = False


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _github_response(published_at: str) -> _FakeResponse:
    body = json.dumps({"tag_name": "v" + __version__,
                       "published_at": published_at}).encode("utf-8")
    return _FakeResponse(body)


class ReleaseDateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        # Background-thread state lives on the module; each test starts
        # from a clean slate so one test's failed fetch cannot throttle
        # the next test's retry.
        release_date._refresh_thread = None
        release_date._last_failed_at = float("-inf")

    def tearDown(self):
        thread = release_date._refresh_thread
        if thread is not None:
            thread.join(timeout=5)
        self.temp.cleanup()

    def _cache_file(self) -> Path:
        return self.data_dir / "release_date.json"

    def _seed_cache(self, version: str = __version__, date: str = "2026-10-30",
                    fetched_at: float | None = None) -> None:
        if fetched_at is None:
            fetched_at = time.time()
        self._cache_file().write_text(
            json.dumps({"version": version, "release_date": date,
                        "fetched_at": fetched_at}), encoding="utf-8")

    def test_version_bump(self):
        self.assertEqual(__version__, "1.1")
        # MemuMusic never shipped a hard-coded date: the offline fallback
        # is empty, and the UI simply shows no date, as before.
        self.assertEqual(RELEASE_DATE, "")

    def test_parse_published_at(self):
        parse = release_date.parse_published_at
        self.assertEqual(parse("2026-10-30T18:22:10Z"), "2026-10-30")
        self.assertEqual(parse("2026-10-30T18:22:10+03:00"), "2026-10-30")
        self.assertEqual(parse("2026-10-30"), "2026-10-30")
        self.assertEqual(parse("2026-10-30 18:22:10"), "2026-10-30")
        for bad in ("", None, "not a date", "2026-13-01T00:00:00Z",
                    "2026-10-30garbage", "2026-10-30T25:00:00Z",
                    "30.10.2026", 20261030):
            self.assertEqual(parse(bad), "", repr(bad))

    def test_release_url_uses_the_updaters_repository(self):
        # updater.py needs httpx, so the repository is compared against its
        # source text instead of an import — the string must stay in sync.
        root = Path(__file__).resolve().parents[1]
        updater_source = (root / "memumusic" / "updater.py").read_text(encoding="utf-8")
        self.assertIn('REPOSITORY = "MemuAI/MemuMusic"', updater_source)
        self.assertEqual(release_date.REPOSITORY, "MemuAI/MemuMusic")
        self.assertEqual(
            release_date.release_url(),
            "https://api.github.com/repos/MemuAI/MemuMusic/releases/tags/v"
            + __version__)

    def test_cache_roundtrip_expiry_and_wrong_version(self):
        now = 1_700_000_000.0
        self.assertEqual(
            release_date.read_cached_release_date(self.data_dir, now=now), "")
        self._seed_cache(fetched_at=now)
        self.assertEqual(
            release_date.read_cached_release_date(self.data_dir, now=now),
            "2026-10-30")
        self.assertEqual(
            release_date.read_cached_release_date(
                self.data_dir, now=now + release_date.CACHE_TTL_SECONDS + 1), "")
        self.assertEqual(
            release_date.read_cached_release_date(
                self.data_dir, version="9.9", now=now), "")

    def test_fresh_cache_wins_and_network_is_never_touched(self):
        self._seed_cache()
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("network must not be used")):
            date, source = release_date.resolve_release_date(self.data_dir)
        self.assertEqual((date, source), ("2026-10-30", "github"))

    def test_offline_falls_back(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("offline")):
            started = time.monotonic()
            date, source = release_date.resolve_release_date(self.data_dir)
            elapsed = time.monotonic() - started
            # The mock must stay in place until the background thread
            # finishes, or the thread would reach the real network.
            thread = release_date._refresh_thread
            if thread is not None:
                thread.join(timeout=5)
        self.assertEqual((date, source), (RELEASE_DATE, "fallback"))
        self.assertLess(elapsed, 1.0, "resolve must not wait for the network")
        self.assertFalse(self._cache_file().exists(),
                         "a failed fetch must not be cached")

    def test_background_fetch_does_not_block_the_caller(self):
        calls = []
        main_thread = threading.get_ident()

        def slow_fetch(request, timeout=None):
            calls.append(threading.get_ident())
            time.sleep(0.5)
            return _github_response("2026-11-02T09:00:00Z")

        with patch("urllib.request.urlopen", side_effect=slow_fetch):
            started = time.monotonic()
            date, source = release_date.resolve_release_date(self.data_dir)
            elapsed = time.monotonic() - started
            thread = release_date._refresh_thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)
        self.assertEqual((date, source), (RELEASE_DATE, "fallback"))
        self.assertLess(elapsed, 0.3, "the caller must return before the fetch")
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], main_thread,
                            "the fetch must run in a background thread")
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            release_date.read_cached_release_date(self.data_dir), "2026-11-02")
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("network must not be used")):
            date, source = release_date.resolve_release_date(self.data_dir)
        self.assertEqual((date, source), ("2026-11-02", "github"))


@unittest.skipUnless(_HAS_SERVER_DEPS, "FastAPI/httpx are not installed")
class VersionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.previous = os.environ.get("MEMUMUSIC_DATA_DIR")
        os.environ["MEMUMUSIC_DATA_DIR"] = str(self.root / "profile")
        release_date._refresh_thread = None
        release_date._last_failed_at = float("-inf")
        from memumusic.server import create_app
        self.client = TestClient(create_app())
        self.client.get("/")

    def tearDown(self):
        self.client.close()
        thread = release_date._refresh_thread
        if thread is not None:
            thread.join(timeout=5)
        if self.previous is None:
            os.environ.pop("MEMUMUSIC_DATA_DIR", None)
        else:
            os.environ["MEMUMUSIC_DATA_DIR"] = self.previous
        self.temp.cleanup()

    def test_health_and_version_report_the_bumped_version(self):
        profile = Path(os.environ["MEMUMUSIC_DATA_DIR"])
        (profile / "release_date.json").write_text(
            json.dumps({"version": __version__, "release_date": "2026-10-30",
                        "fetched_at": time.time()}), encoding="utf-8")
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["version"], "1.1")
        self.assertEqual(health.json()["release_date"], "2026-10-30")
        info = self.client.get("/api/version")
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json(), {"version": "1.1",
                                       "release_date": "2026-10-30",
                                       "release_date_source": "github"})

    def test_version_endpoint_fetches_in_the_background(self):
        with patch("urllib.request.urlopen",
                   return_value=_github_response("2026-11-02T09:00:00Z")):
            first = self.client.get("/api/version").json()
            self.assertEqual(first["version"], "1.1")
            self.assertEqual(first["release_date_source"], "fallback")
            deadline = time.monotonic() + 5
            info = first
            while time.monotonic() < deadline:
                info = self.client.get("/api/version").json()
                if info["release_date_source"] == "github":
                    break
                time.sleep(0.1)
        self.assertEqual(info["release_date"], "2026-11-02")
        self.assertEqual(info["release_date_source"], "github")


if __name__ == "__main__":
    unittest.main()
