# Drives the GUI on Windows: opens it, presses one button through its --selftest hook,
# screenshots the window, and fails unless the run succeeded. CI runs it against the
# installed MSI.
#   test\gui_selftest.ps1 -Gui "C:\Program Files\Deck Narrator\deck-narrator-gui.exe" -Mode video -Deck test\test-deck.pptx -Shot gui-video.png
param(
    [Parameter(Mandatory)] [string]$Gui,
    [Parameter(Mandatory)] [ValidateSet("video", "builds", "check", "phonemes", "sample")] [string]$Mode,
    [Parameter(Mandatory)] [string]$Deck,
    [Parameter(Mandatory)] [string]$Shot,
    [int]$TimeoutSeconds = 900
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$result = Join-Path $env:TEMP "gui-selftest-$Mode.txt"
Remove-Item $result -ErrorAction SilentlyContinue
$deckPath = (Resolve-Path $Deck).Path
# Keep the window up 8 s after the job ends, for the screenshot.
$p = Start-Process -FilePath $Gui -ArgumentList @("--selftest", $Mode, "`"$deckPath`"", "`"$result`"", "8") -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not (Test-Path $result) -and -not $p.HasExited) {
    if ((Get-Date) -gt $deadline) { $p | Stop-Process -Force; throw "GUI $Mode run timed out" }
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds 2
if (-not $p.HasExited) {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path (Get-Location) $Shot))
}
$p.WaitForExit(60000) | Out-Null
if (-not (Test-Path $result)) { throw "GUI exited without a result (exit $($p.ExitCode))" }
$text = Get-Content $result -Raw -Encoding utf8
Write-Host $text
if ($text -notmatch "^exit 0") { throw "GUI $Mode run failed" }
if ($p.ExitCode -ne 0) { throw "GUI exited $($p.ExitCode)" }
if ($Mode -eq "video") {
    if ($text -notmatch "(?m)^video (.+\.mp4)\s*$") { throw "GUI reported no video" }
    $mp4 = $Matches[1].Trim()
    if (-not (Test-Path $mp4) -or (Get-Item $mp4).Length -lt 10000) { throw "video missing or tiny: $mp4" }
    Write-Host "OK: GUI made $mp4 ($((Get-Item $mp4).Length) bytes)"
}
