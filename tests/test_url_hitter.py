from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import url_hitter
from url_hitter import ConfigError, UrlHitter, UrlHitterConfig, read_urls_file


class ConfigTests(unittest.TestCase):
    def test_from_dict_uses_inline_urls(self) -> None:
        config = UrlHitterConfig.from_dict(
            {"urls": ["https://a.test", " https://b.test "], "min_interval_seconds": 5}
        )
        self.assertEqual(config.urls, ["https://a.test", "https://b.test"])
        self.assertEqual(config.min_interval_seconds, 5)

    def test_urls_file_skips_blanks_and_comments(self) -> None:
        path = ROOT / "urls.example.txt"
        urls = read_urls_file(path)
        self.assertTrue(urls)
        self.assertNotIn("", urls)
        self.assertFalse(any(u.startswith("#") for u in urls))

    def test_empty_urls_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            UrlHitterConfig(urls=[])

    def test_max_must_be_at_least_min(self) -> None:
        with self.assertRaises(ConfigError):
            UrlHitterConfig(
                urls=["https://a.test"],
                min_interval_seconds=10,
                max_interval_seconds=5,
            )

    def test_negative_duration_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            UrlHitterConfig(urls=["https://a.test"], duration_hours=-1)

    def test_zero_duration_runs_forever(self) -> None:
        config = UrlHitterConfig(urls=["https://a.test"], duration_hours=0)
        self.assertTrue(config.runs_forever)


class ZeroRandom:
    """Deterministic rng: no waiting between hits."""

    def uniform(self, _a: float, _b: float) -> float:
        return 0.0


class WorkerTests(unittest.TestCase):
    def test_round_robins_urls_and_stops_after_limit(self) -> None:
        config = UrlHitterConfig(
            urls=["https://a.test", "https://b.test"],
            min_interval_seconds=1,
            max_interval_seconds=1,
        )
        events: list = []
        calls: list = []

        hitter: UrlHitter

        def fake_fetch(url: str, _timeout: int, _agent: str) -> int:
            calls.append(url)
            if len(calls) >= 4:
                hitter.stop(join=False)
            return 200

        hitter = UrlHitter(
            config,
            on_event=lambda kind, **info: events.append((kind, info)),
            fetch=fake_fetch,
            rng=ZeroRandom(),
        )
        hitter.start()
        hitter._thread.join(timeout=5)  # type: ignore[union-attr]

        self.assertFalse(hitter.is_running())
        self.assertEqual(calls[:4], [
            "https://a.test",
            "https://b.test",
            "https://a.test",
            "https://b.test",
        ])
        self.assertEqual(hitter.hit_count, 4)
        kinds = [kind for kind, _ in events]
        self.assertEqual(kinds[0], "started")
        self.assertEqual(kinds[-1], "stopped")

    def test_errors_are_reported_and_do_not_crash(self) -> None:
        config = UrlHitterConfig(urls=["https://a.test"])
        events: list = []
        hitter: UrlHitter

        def failing_fetch(_url: str, _timeout: int, _agent: str) -> int:
            hitter.stop(join=False)
            raise RuntimeError("boom")

        hitter = UrlHitter(
            config,
            on_event=lambda kind, **info: events.append((kind, info)),
            fetch=failing_fetch,
            rng=ZeroRandom(),
        )
        hitter.start()
        hitter._thread.join(timeout=5)  # type: ignore[union-attr]

        kinds = [kind for kind, _ in events]
        self.assertIn("error", kinds)
        self.assertEqual(hitter.hit_count, 0)


class CliTests(unittest.TestCase):
    def test_version_flag(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "url_hitter.py"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), f"url_hitter.py {url_hitter.VERSION}")

    def test_help_lists_flags(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "url_hitter.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--config", result.stdout)
        self.assertIn("--url", result.stdout)
        self.assertIn("--hours", result.stdout)

    def test_missing_urls_errors_out(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "url_hitter.py"),
                "--config",
                str(ROOT / "does-not-exist.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
