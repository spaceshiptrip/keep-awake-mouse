# Mouse Mover

A tiny Python app that jiggles the mouse every configurable number of seconds.
The default interval is 20 seconds.

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
