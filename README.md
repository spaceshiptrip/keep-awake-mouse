# Mouse Mover

A tiny Python app that jiggles the mouse every configurable number of seconds.
The default interval is 20 seconds.

The default interface is a small Tk dialog built with Python's standard
`tkinter` and `ttk` widgets. When the mover is running, the dialog shows:

- the installed app version in the title and heading
- a status line such as `Running every 20 seconds`
- a green activity bar that fills during each interval and resets after every
  jiggle
- a jiggle counter

## Run

```sh
source .venv/bin/activate
python mouse_mover.py
```

If your Python was built without Tk support, the same command runs in terminal
mode automatically. You can also force terminal mode:

```sh
source .venv/bin/activate
python mouse_mover.py --cli --interval 20
```

## URL Refresher

The app can also hit a list of URLs at random intervals in the background to keep
sessions or dashboards warm. It uses only Python's standard library (`urllib`) —
there is no browser, so page JavaScript is **not** executed. Each refresh is a plain
GET per URL, which is enough to keep endpoints and sessions alive.

### Configure the URLs

Create a `url_config.json` next to the app (copy `url_config.example.json`):

```json
{
  "urls": ["https://example.com/", "https://httpbin.org/get"],
  "urls_file": "urls.txt",
  "min_interval_seconds": 60,
  "max_interval_seconds": 300,
  "duration_hours": 0,
  "timeout_seconds": 15
}
```

- Provide URLs inline via `urls`, or point `urls_file` at a text file with one URL
  per line (blank lines and `#` comments are ignored — see `urls.example.txt`).
- Each cycle waits a random number of seconds between `min_interval_seconds` and
  `max_interval_seconds`.
- `duration_hours` is how long to run; **`0` means run until you stop it.**

Your personal `url_config.json` and `urls.txt` are gitignored.

### Run it standalone

```sh
python url_hitter.py --config url_config.json
```

Or without a config file:

```sh
python url_hitter.py --url https://example.com/ --url https://httpbin.org/get --min 30 --max 120 --hours 2
```

Each refresh prints a line like `[3] 19:02:38 refreshed https://example.com/ → 200`.
Stop it with `Ctrl+C`.

### From the dialog

The Tk dialog has a **URL Refresher** section below the mouse controls, independent
of the jiggle. It reads `url_config.json` for the URL list, lets you set the min/max
seconds and the number of hours (0 = until stopped), and has a single button to turn
it on and off. A status line shows each URL as it is refreshed, plus a hit counter.

## Windows PowerShell Script

For a simple Windows-only keep-awake helper, run the included PowerShell script:

```powershell
powershell -ExecutionPolicy Bypass -File .\keep-awake.ps1
```

The default interval is 20 seconds. To use a different interval:

```powershell
powershell -ExecutionPolicy Bypass -File .\keep-awake.ps1 -IntervalSeconds 10
```

The script nudges the mouse 1 pixel, waits briefly, then moves it back so the
cursor does not drift. Leave the PowerShell window open while you want the
machine kept awake. Stop it with `Ctrl+C`.

To start it hidden from another PowerShell session:

```powershell
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\jtorres\keep-awake-mouse\keep-awake.ps1"'
```

To stop a hidden instance:

```powershell
$needle = 'keep-awake.ps1'
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*$needle*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Tk UI Requirements

The default dialog requires a Python install with working Tk support. If Python
can import `tkinter` but fails to import `_tkinter`, the app will run in terminal
mode instead of opening the dialog.

Check your active Python with:

```sh
python -c 'import tkinter; print("tkinter ok", tkinter.TkVersion)'
```

On macOS with Homebrew Python, install the matching `python-tk` package for your
Python version. For example, this repo's Python 3.13 virtual environment needs:

```sh
brew install python-tk@3.13
```

Then reinstall the uv tool with the Tk-capable Python if needed:

```sh
uv tool install --force --python .venv/bin/python .
```

## Install with uv

This repo can be installed as a uv tool, which creates a `mouse-mover` command
in `~/.local/bin`. This is the recommended install style for this app because
it provides a normal executable command without bundling Python into a separate
desktop app:

```sh
uv tool install .
mouse-mover
```

To run in terminal mode:

```sh
mouse-mover --cli --interval 20
```

Check the installed version:

```sh
mouse-mover --version
```

After changing this repo, reinstall the command:

```sh
uv tool install --force .
```

Make sure `~/.local/bin` is on your `PATH`.

## Versioning

The current app version is `0.2.0`.

The version is visible in two places:

- `mouse-mover --version`
- the Tk dialog window title and main heading

If the installed command does not show the expected version, reinstall with:

```sh
uv tool install --force .
```

When changing the app version, keep these values in sync:

- `VERSION` in `mouse_mover.py`
- `VERSION` in `url_hitter.py`
- `version` in `pyproject.toml`

The test suite checks that these match.

## Tests

Run the tests with:

```sh
python -m unittest discover
```

The tests cover:

- `--version` and `--help` for both `mouse_mover.py` and `url_hitter.py`
- invalid interval validation
- the uv console script entry points
- package version consistency
- progress/default UI constants
- URL config parsing, validation, and the background worker (with a fake fetcher)

## Platform Support

- macOS: uses CoreGraphics to move the cursor and IOKit power assertions to ask
  macOS to keep the display awake. It does not call `caffeinate`.
- Windows: uses `user32` to move the cursor and `SetThreadExecutionState` to ask
  Windows to keep the display awake.

If macOS blocks power assertions by policy, the app still runs and jiggles the
cursor. The status line will show that the awake guard is unavailable.

## macOS Permissions

If the pointer does not move, allow the terminal or Python app in:

`System Settings > Privacy & Security > Accessibility`
