#!/usr/bin/env python3
"""Small cross-platform mouse jiggler.

The app uses only Python's standard library. It prefers native APIs where
available and falls back cleanly when the current platform is unsupported.
"""

from __future__ import annotations

import ctypes
import argparse
import platform
import queue
import signal
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    tk = None
    messagebox = None
    ttk = None

from url_hitter import (
    ConfigError,
    UrlHitter,
    UrlHitterConfig,
    DEFAULT_CONFIG_NAME,
    DEFAULT_MAX_INTERVAL_SECONDS,
    DEFAULT_MIN_INTERVAL_SECONDS,
)


DEFAULT_INTERVAL_SECONDS = 20
PROGRESS_BAR_HEIGHT = 14
WINDOW_WIDTH = 380
VERSION = "0.2.0"


class MouseMoveError(RuntimeError):
    """Raised when the current platform cannot move the mouse."""


class MouseBackend:
    """Platform-specific mouse movement and sleep-prevention helpers."""

    def __init__(self) -> None:
        self.system = platform.system().lower()
        self._power_assertion_id: Optional[ctypes.c_uint32] = None
        self._core_graphics = None
        self._core_foundation = None
        self._iokit = None
        self._user32 = None

        if self.system == "darwin":
            self._setup_macos()
        elif self.system == "windows":
            self._setup_windows()

    @property
    def name(self) -> str:
        if self.system == "darwin":
            return "macOS"
        if self.system == "windows":
            return "Windows"
        return platform.system() or "Unsupported OS"

    def is_supported(self) -> bool:
        return self.system in {"darwin", "windows"}

    def start_awake_guard(self) -> None:
        if self.system == "darwin":
            self._start_macos_awake_guard()
        elif self.system == "windows":
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x1 | 0x2)

    def stop_awake_guard(self) -> None:
        if self.system == "darwin" and self._power_assertion_id is not None:
            self._iokit.IOPMAssertionRelease(self._power_assertion_id)
            self._power_assertion_id = None
        elif self.system == "windows":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

    def jiggle(self) -> None:
        if self.system == "darwin":
            self._jiggle_macos()
        elif self.system == "windows":
            self._jiggle_windows()
        else:
            raise MouseMoveError(f"Mouse movement is not implemented for {platform.system()}.")

    def _setup_macos(self) -> None:
        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        self._CGPoint = CGPoint
        core_graphics = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        core_graphics.CGEventCreate.argtypes = [ctypes.c_void_p]
        core_graphics.CGEventCreate.restype = ctypes.c_void_p
        core_graphics.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        core_graphics.CGEventGetLocation.restype = CGPoint
        core_graphics.CFRelease.argtypes = [ctypes.c_void_p]
        core_graphics.CFRelease.restype = None
        core_graphics.CGWarpMouseCursorPosition.argtypes = [CGPoint]
        core_graphics.CGWarpMouseCursorPosition.restype = ctypes.c_int
        self._core_graphics = core_graphics

        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        core_foundation.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        core_foundation.CFRelease.restype = None
        self._core_foundation = core_foundation

        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOPMAssertionCreateWithName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
        iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        iokit.IOPMAssertionRelease.restype = ctypes.c_int
        self._iokit = iokit

    def _setup_windows(self) -> None:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        self._POINT = POINT
        self._user32 = ctypes.windll.user32

    def _jiggle_macos(self) -> None:
        event = self._core_graphics.CGEventCreate(None)
        if not event:
            raise MouseMoveError("Could not read the current mouse position.")

        try:
            point = self._core_graphics.CGEventGetLocation(event)
            self._core_graphics.CGWarpMouseCursorPosition(
                self._CGPoint(point.x + 1.0, point.y)
            )
            self._core_graphics.CGWarpMouseCursorPosition(point)
        finally:
            self._core_graphics.CFRelease(event)

    def _start_macos_awake_guard(self) -> None:
        if self._power_assertion_id is not None:
            return

        encoding_utf8 = 0x08000100
        assertion_type = self._core_foundation.CFStringCreateWithCString(
            None, b"NoDisplaySleepAssertion", encoding_utf8
        )
        reason = self._core_foundation.CFStringCreateWithCString(
            None, b"Mouse Mover is running", encoding_utf8
        )
        if not assertion_type or not reason:
            raise MouseMoveError("Could not create macOS power assertion strings.")

        assertion_id = ctypes.c_uint32(0)
        try:
            result = self._iokit.IOPMAssertionCreateWithName(
                assertion_type,
                255,  # kIOPMAssertionLevelOn
                reason,
                ctypes.byref(assertion_id),
            )
        finally:
            self._core_foundation.CFRelease(assertion_type)
            self._core_foundation.CFRelease(reason)

        if result != 0:
            raise MouseMoveError(f"macOS rejected the power assertion with code {result}.")

        self._power_assertion_id = assertion_id

    def _jiggle_windows(self) -> None:
        point = self._POINT()
        if not self._user32.GetCursorPos(ctypes.byref(point)):
            raise MouseMoveError("Could not read the current mouse position.")

        self._user32.SetCursorPos(point.x + 1, point.y)
        self._user32.SetCursorPos(point.x, point.y)


class MouseMoverApp(tk.Tk if tk is not None else object):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Mouse Mover {VERSION}")
        self.resizable(False, False)

        self.backend = MouseBackend()
        self.running = False
        self.after_id: Optional[str] = None
        self.progress_after_id: Optional[str] = None
        self.progress_started_at = 0.0
        self.progress_interval = DEFAULT_INTERVAL_SECONDS
        self.jiggle_count = 0
        self.awake_guard_available = True

        self.interval_var = tk.StringVar(value=str(DEFAULT_INTERVAL_SECONDS))
        self.status_var = tk.StringVar(value=f"Ready on {self.backend.name}")
        self.count_var = tk.StringVar(value="Jiggles: 0")

        # URL Refresher state (runs independently of the mouse jiggle).
        self.url_hitter: Optional[UrlHitter] = None
        self.url_event_queue: "queue.Queue[tuple]" = queue.Queue()
        self.url_poll_after_id: Optional[str] = None
        self.url_config_path = Path(__file__).resolve().parent / DEFAULT_CONFIG_NAME
        loaded = self._load_url_config()
        self.url_min_var = tk.StringVar(
            value=str(loaded.min_interval_seconds if loaded else DEFAULT_MIN_INTERVAL_SECONDS)
        )
        self.url_max_var = tk.StringVar(
            value=str(loaded.max_interval_seconds if loaded else DEFAULT_MAX_INTERVAL_SECONDS)
        )
        self.url_hours_var = tk.StringVar(
            value=str(int(loaded.duration_hours) if loaded else 0)
        )
        self.url_status_var = tk.StringVar(value=self._initial_url_status(loaded))
        self.url_count_var = tk.StringVar(value="URL hits: 0")

        self._build_ui()
        self.update_idletasks()
        self.geometry(f"{WINDOW_WIDTH}x{self.winfo_reqheight()}")
        self.minsize(WINDOW_WIDTH, self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.backend.is_supported():
            self.status_var.set(f"{self.backend.name} is not supported")
            self.start_button.configure(state=tk.DISABLED)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(frame, text=f"Mouse Mover {VERSION}", font=("", 18, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            frame,
            text="Jiggles the pointer and asks the OS to keep the display awake.",
            wraplength=315,
        )
        subtitle.pack(anchor=tk.W, pady=(4, 18))

        input_row = ttk.Frame(frame)
        input_row.pack(fill=tk.X)

        ttk.Label(input_row, text="Every").pack(side=tk.LEFT)
        interval_entry = ttk.Entry(input_row, width=8, textvariable=self.interval_var)
        interval_entry.pack(side=tk.LEFT, padx=8)
        ttk.Label(input_row, text="seconds").pack(side=tk.LEFT)

        button_row = ttk.Frame(frame)
        button_row.pack(fill=tk.X, pady=18)

        self.start_button = ttk.Button(button_row, text="Start", command=self.start)
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.stop_button = ttk.Button(
            button_row, text="Stop", command=self.stop, state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        ttk.Label(frame, textvariable=self.status_var, wraplength=315).pack(anchor=tk.W)
        self.progress_canvas = tk.Canvas(
            frame,
            height=PROGRESS_BAR_HEIGHT,
            highlightthickness=0,
            background="#d7d7d7",
        )
        self.progress_canvas.pack(fill=tk.X, pady=(10, 2))
        self.progress_fill = self.progress_canvas.create_rectangle(
            0,
            0,
            0,
            PROGRESS_BAR_HEIGHT,
            fill="#22a447",
            outline="",
        )
        self.progress_canvas.bind("<Configure>", self._resize_progress)
        ttk.Label(frame, textvariable=self.count_var).pack(anchor=tk.W, pady=(6, 0))

        self._build_url_ui(frame)

    def _build_url_ui(self, frame: "ttk.Frame") -> None:
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(18, 12))

        ttk.Label(frame, text="URL Refresher", font=("", 13, "bold")).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="Hits a list of URLs at random intervals in the background.",
            wraplength=315,
        ).pack(anchor=tk.W, pady=(2, 10))

        every_row = ttk.Frame(frame)
        every_row.pack(fill=tk.X)
        ttk.Label(every_row, text="Every").pack(side=tk.LEFT)
        ttk.Entry(every_row, width=6, textvariable=self.url_min_var).pack(
            side=tk.LEFT, padx=(8, 4)
        )
        ttk.Label(every_row, text="to").pack(side=tk.LEFT)
        ttk.Entry(every_row, width=6, textvariable=self.url_max_var).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(every_row, text="seconds").pack(side=tk.LEFT)

        hours_row = ttk.Frame(frame)
        hours_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(hours_row, text="For").pack(side=tk.LEFT)
        ttk.Entry(hours_row, width=6, textvariable=self.url_hours_var).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Label(hours_row, text="hours (0 = until stopped)").pack(side=tk.LEFT)

        self.url_toggle_button = ttk.Button(
            frame, text="Start URL Refresher", command=self.toggle_url_hitter
        )
        self.url_toggle_button.pack(fill=tk.X, pady=12)

        ttk.Label(frame, textvariable=self.url_status_var, wraplength=315).pack(
            anchor=tk.W
        )
        ttk.Label(frame, textvariable=self.url_count_var).pack(anchor=tk.W, pady=(6, 0))

    def start(self) -> None:
        interval = self._read_interval()
        if interval is None:
            return

        self.awake_guard_available = True
        try:
            self.backend.start_awake_guard()
        except Exception as exc:  # noqa: BLE001 - GUI should show native API failures.
            self.awake_guard_available = False

        self.running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.progress_canvas.configure(background="#cfead6")
        self._set_running_status(interval)
        self._start_progress(interval)
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        if self.progress_after_id is not None:
            self.after_cancel(self.progress_after_id)
            self.progress_after_id = None

        self.backend.stop_awake_guard()
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.progress_canvas.configure(background="#d7d7d7")
        self._set_progress_fraction(0.0)
        self.status_var.set("Stopped")

    def _tick(self) -> None:
        if not self.running:
            return

        interval = self._read_interval(show_error=False) or DEFAULT_INTERVAL_SECONDS
        try:
            self.backend.jiggle()
            self.jiggle_count += 1
            self.count_var.set(f"Jiggles: {self.jiggle_count}")
            self._set_running_status(interval)
            self._start_progress(interval)
        except Exception as exc:  # noqa: BLE001 - GUI should show native API failures.
            self.stop()
            messagebox.showerror("Mouse Mover", f"Could not move the mouse:\n{exc}")
            return

        self.after_id = self.after(interval * 1000, self._tick)

    def _start_progress(self, interval: int) -> None:
        if self.progress_after_id is not None:
            self.after_cancel(self.progress_after_id)
            self.progress_after_id = None

        self.progress_started_at = time.monotonic()
        self.progress_interval = interval
        self._update_progress()

    def _update_progress(self) -> None:
        if not self.running:
            return

        elapsed = time.monotonic() - self.progress_started_at
        fraction = min(elapsed / self.progress_interval, 1.0)
        self._set_progress_fraction(fraction)
        self.progress_after_id = self.after(100, self._update_progress)

    def _set_progress_fraction(self, fraction: float) -> None:
        width = self.progress_canvas.winfo_width()
        fill_width = max(0, width * fraction)
        if self.running:
            fill_width = max(12, fill_width)

        self.progress_canvas.coords(
            self.progress_fill,
            0,
            0,
            fill_width,
            PROGRESS_BAR_HEIGHT,
        )

    def _resize_progress(self, _event: tk.Event) -> None:
        if self.running:
            elapsed = time.monotonic() - self.progress_started_at
            self._set_progress_fraction(min(elapsed / self.progress_interval, 1.0))
        else:
            self._set_progress_fraction(0.0)

    def _read_interval(self, show_error: bool = True) -> Optional[int]:
        try:
            interval = int(self.interval_var.get())
        except ValueError:
            if show_error:
                messagebox.showerror("Mouse Mover", "Interval must be a whole number.")
            return None

        if interval < 1:
            if show_error:
                messagebox.showerror("Mouse Mover", "Interval must be at least 1 second.")
            return None

        return interval

    def _set_running_status(self, interval: int) -> None:
        suffix = "" if self.awake_guard_available else " (awake guard unavailable)"
        self.status_var.set(f"Running every {interval} seconds{suffix}")

    # ------------------------------------------------------------------
    # URL Refresher
    # ------------------------------------------------------------------
    def _load_url_config(self) -> Optional[UrlHitterConfig]:
        if not self.url_config_path.exists():
            return None
        try:
            return UrlHitterConfig.from_config_file(self.url_config_path)
        except ConfigError:
            return None

    def _initial_url_status(self, loaded: Optional[UrlHitterConfig]) -> str:
        if loaded is None:
            return f"No {self.url_config_path.name} found next to the app."
        return f"Ready: {len(loaded.urls)} url(s) from {self.url_config_path.name}"

    def toggle_url_hitter(self) -> None:
        if self.url_hitter is not None and self.url_hitter.is_running():
            self.stop_url_hitter()
        else:
            self.start_url_hitter()

    def start_url_hitter(self) -> None:
        loaded = self._load_url_config()
        if loaded is None or not loaded.urls:
            messagebox.showerror(
                "URL Refresher",
                f"No URLs found. Create {self.url_config_path.name} (see "
                "url_config.example.json) next to the app.",
            )
            return

        try:
            config = UrlHitterConfig(
                urls=loaded.urls,
                min_interval_seconds=int(self.url_min_var.get()),
                max_interval_seconds=int(self.url_max_var.get()),
                duration_hours=float(self.url_hours_var.get()),
                timeout_seconds=loaded.timeout_seconds,
                user_agent=loaded.user_agent,
            )
        except (ValueError, ConfigError) as exc:
            messagebox.showerror("URL Refresher", str(exc))
            return

        # The worker runs on a background thread; it must not touch Tk directly,
        # so events are marshalled back through a queue drained on the main loop.
        self.url_hitter = UrlHitter(
            config, on_event=lambda kind, **info: self.url_event_queue.put((kind, info))
        )
        self.url_hitter.start()
        self.url_toggle_button.configure(text="Stop URL Refresher")
        self._poll_url_events()

    def stop_url_hitter(self) -> None:
        if self.url_hitter is not None:
            self.url_hitter.stop(join=False)
        self.url_toggle_button.configure(text="Start URL Refresher")

    def _poll_url_events(self) -> None:
        try:
            while True:
                kind, info = self.url_event_queue.get_nowait()
                self._handle_url_event(kind, info)
        except queue.Empty:
            pass

        if self.url_hitter is not None and self.url_hitter.is_running():
            self.url_poll_after_id = self.after(150, self._poll_url_events)
        else:
            self.url_poll_after_id = None

    def _handle_url_event(self, kind: str, info: dict) -> None:
        if kind == "started":
            window = (
                "until stopped"
                if info.get("duration_hours", 0) == 0
                else f"for {info['duration_hours']:g}h"
            )
            self.url_status_var.set(
                f"Hitting {info['url_count']} url(s) every "
                f"{info['min_interval']}–{info['max_interval']}s, {window}."
            )
        elif kind == "hit":
            self.url_count_var.set(f"URL hits: {info['count']}")
            timestamp = time.strftime("%H:%M:%S")
            self.url_status_var.set(
                f"{timestamp} refreshed {info['url']} → {info['status']}"
            )
        elif kind == "error":
            self.url_status_var.set(f"Error on {info['url']}: {info['message']}")
        elif kind == "stopped":
            self.url_status_var.set(f"Stopped ({info['reason']}).")
            self.url_toggle_button.configure(text="Start URL Refresher")

    def _on_close(self) -> None:
        if self.running:
            self.stop()
        if self.url_hitter is not None:
            self.url_hitter.stop(join=False)
        self.destroy()


def run_cli(interval: int) -> None:
    backend = MouseBackend()
    if not backend.is_supported():
        raise SystemExit(f"{backend.name} is not supported.")

    running = True
    awake_guard_available = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        backend.start_awake_guard()
    except Exception as exc:  # noqa: BLE001 - terminal fallback should keep jiggling.
        awake_guard_available = False
        print(f"Awake guard unavailable: {exc}", file=sys.stderr)

    guard_status = "" if awake_guard_available else " (awake guard unavailable)"
    print(f"Mouse Mover running every {interval} seconds{guard_status}. Press Ctrl-C to stop.")

    jiggle_count = 0
    try:
        while running:
            backend.jiggle()
            jiggle_count += 1
            print(f"Jiggles: {jiggle_count}", flush=True)
            for _ in range(interval * 10):
                if not running:
                    break
                time.sleep(0.1)
    except MouseMoveError as exc:
        raise SystemExit(f"Could not move the mouse: {exc}") from exc
    finally:
        backend.stop_awake_guard()
        print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Jiggle the mouse every N seconds to keep the computer awake."
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between jiggles, default {DEFAULT_INTERVAL_SECONDS}",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="run in the terminal instead of opening the Tk GUI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    args = parser.parse_args()

    if args.interval < 1:
        parser.error("--interval must be at least 1")

    if tk is not None and not args.cli:
        app = MouseMoverApp()
        app.interval_var.set(str(args.interval))
        app.mainloop()
    else:
        run_cli(args.interval)


if __name__ == "__main__":
    main()
