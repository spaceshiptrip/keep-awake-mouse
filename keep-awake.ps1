param(
    [int]$IntervalSeconds = 20
)

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class MouseJiggler {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
}
"@

Write-Host "Keeping laptop awake by nudging the mouse every $IntervalSeconds seconds. Press Ctrl+C to stop."

while ($true) {
    $point = New-Object MouseJiggler+POINT
    [MouseJiggler]::GetCursorPos([ref]$point) | Out-Null

    [MouseJiggler]::SetCursorPos($point.X + 1, $point.Y) | Out-Null
    Start-Sleep -Milliseconds 150
    [MouseJiggler]::SetCursorPos($point.X, $point.Y) | Out-Null

    Start-Sleep -Seconds $IntervalSeconds
}
