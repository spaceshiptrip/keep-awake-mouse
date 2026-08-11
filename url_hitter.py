#!/usr/bin/env python3
"""Hit a list of URLs at random intervals to keep sessions warm.

Standard-library only (matches the rest of this project): URLs are fetched with
``urllib.request`` -- there is no browser and no page JavaScript is executed.

The worker runs on a background thread so it can be driven either from the
command line or from the Mouse Mover Tk dialog without blocking the UI.
"""

from __future__ import annotations

import argparse
import itertools
import json
import signal
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

VERSION = "0.2.0"

DEFAULT_MIN_INTERVAL_SECONDS = 60
DEFAULT_MAX_INTERVAL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_DURATION_HOURS = 0.0  # 0 means run until stopped.
DEFAULT_USER_AGENT = f"keep-awake-url-hitter/{VERSION}"
DEFAULT_CONFIG_NAME = "url_config.json"

# Callback signature: on_event(kind: str, **info) -> None
EventCallback = Callable[..., None]


class ConfigError(ValueError):
    """Raised when a config file or its values are invalid."""


@dataclass
class UrlHitterConfig:
    """Validated settings for a run.

    ``duration_hours == 0`` means "run until stopped".
    """

    urls: List[str]
    min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS
    max_interval_seconds: int = DEFAULT_MAX_INTERVAL_SECONDS
    duration_hours: float = DEFAULT_DURATION_HOURS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        self.urls = [u.strip() for u in self.urls if u and u.strip()]
        if not self.urls:
            raise ConfigError("No URLs to hit. Provide a urls list or a urls_file.")

        self.min_interval_seconds = int(self.min_interval_seconds)
        self.max_interval_seconds = int(self.max_interval_seconds)
        self.timeout_seconds = int(self.timeout_seconds)
        self.duration_hours = float(self.duration_hours)

        if self.min_interval_seconds < 1:
            raise ConfigError("min_interval_seconds must be at least 1.")
        if self.max_interval_seconds < self.min_interval_seconds:
            raise ConfigError(
                "max_interval_seconds must be greater than or equal to "
                "min_interval_seconds."
            )
        if self.timeout_seconds < 1:
            raise ConfigError("timeout_seconds must be at least 1.")
        if self.duration_hours < 0:
            raise ConfigError("duration_hours cannot be negative.")

    @property
    def runs_forever(self) -> bool:
        return self.duration_hours == 0

    @classmethod
    def from_dict(cls, data: dict, base_dir: Optional[Path] = None) -> "UrlHitterConfig":
        base_dir = base_dir or Path.cwd()
        urls = list(data.get("urls") or [])
        urls_file = data.get("urls_file")
        if not urls and urls_file:
            urls = read_urls_file(base_dir / urls_file)

        return cls(
            urls=urls,
            min_interval_seconds=data.get(
                "min_interval_seconds", DEFAULT_MIN_INTERVAL_SECONDS
            ),
            max_interval_seconds=data.get(
                "max_interval_seconds", DEFAULT_MAX_INTERVAL_SECONDS
            ),
            duration_hours=data.get("duration_hours", DEFAULT_DURATION_HOURS),
            timeout_seconds=data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            user_agent=data.get("user_agent", DEFAULT_USER_AGENT),
        )

    @classmethod
    def from_config_file(cls, path: Path) -> "UrlHitterConfig":
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise ConfigError(f"Config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("Config file must contain a JSON object.")
        return cls.from_dict(data, base_dir=path.resolve().parent)


def read_urls_file(path: Path) -> List[str]:
    """Read one URL per line, ignoring blank lines and ``#`` comments."""
    path = Path(path)
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError as exc:
        raise ConfigError(f"URLs file not found: {path}") from exc

    urls: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def _default_fetch(url: str, timeout: int, user_agent: str) -> int:
    """Perform a GET and return the HTTP status code."""
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # Drain the body so the connection closes cleanly, but cap the read.
        response.read(2048)
        return getattr(response, "status", None) or response.getcode()


class UrlHitter:
    """Background worker that cycles through URLs at random intervals."""

    def __init__(
        self,
        config: UrlHitterConfig,
        on_event: Optional[EventCallback] = None,
        fetch: Optional[Callable[[str, int, str], int]] = None,
        rng=None,
    ) -> None:
        self.config = config
        self._on_event = on_event or (lambda *a, **k: None)
        self._fetch = fetch or _default_fetch
        if rng is None:
            import random

            rng = random.Random()
        self._rng = rng

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.hit_count = 0

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self.hit_count = 0
        self._thread = threading.Thread(
            target=self._run, name="url-hitter", daemon=True
        )
        self._thread.start()

    def stop(self, join: bool = True, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if join and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _emit(self, kind: str, **info) -> None:
        try:
            self._on_event(kind, **info)
        except Exception:  # noqa: BLE001 - a bad listener must not kill the worker.
            pass

    def _run(self) -> None:
        cfg = self.config
        deadline = (
            None if cfg.runs_forever else time.monotonic() + cfg.duration_hours * 3600
        )
        self._emit(
            "started",
            url_count=len(cfg.urls),
            min_interval=cfg.min_interval_seconds,
            max_interval=cfg.max_interval_seconds,
            duration_hours=cfg.duration_hours,
        )

        cycle = itertools.cycle(cfg.urls)
        reason = "stopped"
        try:
            while not self._stop_event.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    reason = "duration reached"
                    break

                url = next(cycle)
                try:
                    status = self._fetch(
                        url, cfg.timeout_seconds, cfg.user_agent
                    )
                    self.hit_count += 1
                    self._emit("hit", url=url, status=status, count=self.hit_count)
                except Exception as exc:  # noqa: BLE001 - report and keep going.
                    self._emit("error", url=url, message=str(exc))

                if self._stop_event.is_set():
                    break
                wait = self._rng.uniform(
                    cfg.min_interval_seconds, cfg.max_interval_seconds
                )
                if self._sleep_or_stop(wait):
                    break
        finally:
            self._emit("stopped", reason=reason, count=self.hit_count)

    def _sleep_or_stop(self, seconds: float) -> bool:
        """Sleep in small slices so stop() is responsive. Returns True if stopped."""
        # Event.wait already blocks efficiently and returns True when set.
        return self._stop_event.wait(timeout=seconds)


def _print_event(kind: str, **info) -> None:
    if kind == "started":
        forever = info.get("duration_hours", 0) == 0
        window = (
            "until stopped"
            if forever
            else f"for {info['duration_hours']} hour(s)"
        )
        print(
            f"Hitting {info['url_count']} url(s) every "
            f"{info['min_interval']}-{info['max_interval']}s, {window}. "
            "Press Ctrl-C to stop.",
            flush=True,
        )
    elif kind == "hit":
        timestamp = time.strftime("%H:%M:%S")
        print(
            f"[{info['count']}] {timestamp} refreshed {info['url']} "
            f"→ {info['status']}",
            flush=True,
        )
    elif kind == "error":
        print(f"error hitting {info['url']}: {info['message']}", file=sys.stderr, flush=True)
    elif kind == "stopped":
        print(f"Stopped ({info['reason']}). Total hits: {info['count']}.", flush=True)


def _build_config_from_args(args: argparse.Namespace) -> UrlHitterConfig:
    if args.url:
        config = UrlHitterConfig(urls=list(args.url))
    elif args.urls_file:
        config = UrlHitterConfig(urls=read_urls_file(Path(args.urls_file)))
    else:
        config = UrlHitterConfig.from_config_file(Path(args.config))

    # CLI overrides win over config-file values.
    if args.min is not None:
        config.min_interval_seconds = args.min
    if args.max is not None:
        config.max_interval_seconds = args.max
    if args.hours is not None:
        config.duration_hours = args.hours
    # Re-validate after overrides.
    return UrlHitterConfig(
        urls=config.urls,
        min_interval_seconds=config.min_interval_seconds,
        max_interval_seconds=config.max_interval_seconds,
        duration_hours=config.duration_hours,
        timeout_seconds=config.timeout_seconds,
        user_agent=config.user_agent,
    )


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hit a list of URLs at random intervals using Python's standard "
            "library (no browser)."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to a JSON config file (default {DEFAULT_CONFIG_NAME})",
    )
    source.add_argument(
        "--urls-file",
        help="path to a text file with one URL per line",
    )
    source.add_argument(
        "--url",
        action="append",
        help="a URL to hit; may be repeated",
    )
    parser.add_argument(
        "--min", type=int, help="minimum seconds between hits (overrides config)"
    )
    parser.add_argument(
        "--max", type=int, help="maximum seconds between hits (overrides config)"
    )
    parser.add_argument(
        "--hours",
        type=float,
        help="how many hours to run; 0 means until stopped (overrides config)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    try:
        config = _build_config_from_args(args)
    except ConfigError as exc:
        parser.error(str(exc))

    hitter = UrlHitter(config, on_event=_print_event)

    def handle_stop(_signum: int, _frame: object) -> None:
        hitter.stop(join=False)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    hitter.start()
    # Keep the main thread alive until the worker finishes (duration reached or
    # a signal set the stop event).
    while hitter.is_running():
        time.sleep(0.2)


if __name__ == "__main__":
    main()
