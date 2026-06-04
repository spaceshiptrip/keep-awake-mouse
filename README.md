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

The current app version is `0.1.1`.

The version is visible in two places:

- `mouse-mover --version`
- the Tk dialog window title and main heading

If the installed command does not show the expected version, reinstall with:

```sh
uv tool install --force .
```

When changing the app version, keep these values in sync:

- `VERSION` in `mouse_mover.py`
- `version` in `pyproject.toml`

The test suite checks that these match.

## Tests

Run the tests with:

```sh
python -m unittest discover
```

The tests cover:

- `--version`
- `--help`
- invalid interval validation
- the uv console script entry point
- package version consistency
- progress/default UI constants

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
