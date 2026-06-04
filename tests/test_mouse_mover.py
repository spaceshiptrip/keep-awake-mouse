from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


class MouseMoverTests(unittest.TestCase):
    def test_version_flag_reports_app_version(self) -> None:
        import mouse_mover

        result = subprocess.run(
            [sys.executable, str(ROOT / "mouse_mover.py"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), f"mouse_mover.py {mouse_mover.VERSION}")

    def test_help_includes_version_flag_without_starting_app(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "mouse_mover.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--version", result.stdout)
        self.assertIn("--cli", result.stdout)

    def test_invalid_interval_exits_before_starting_app(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "mouse_mover.py"), "--cli", "--interval", "0"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--interval must be at least 1", result.stderr)

    def test_pyproject_version_and_console_script_match_app(self) -> None:
        import mouse_mover

        data = tomllib.loads((ROOT / "pyproject.toml").read_text())

        self.assertEqual(data["project"]["version"], mouse_mover.VERSION)
        self.assertEqual(
            data["project"]["scripts"]["mouse-mover"],
            "mouse_mover:main",
        )

    def test_dialog_constants_show_visible_progress_and_extra_height(self) -> None:
        import mouse_mover

        self.assertEqual(mouse_mover.PROGRESS_BAR_HEIGHT, 14)
        self.assertEqual(mouse_mover.DEFAULT_INTERVAL_SECONDS, 20)


if __name__ == "__main__":
    unittest.main()
