# One-time, re-runnable setup for deck-narrator on Windows 10/11. Native PowerShell:
# no WSL, no Docker.
#   .\setup.ps1              LibreOffice + ffmpeg (winget), uv, Python deps in .\.venv
#   .\setup.ps1 -AddToPath   also put this folder on your user PATH, so `deck-narrator` works anywhere
param([switch]$AddToPath)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

# Native commands don't stop the script on failure, even with ErrorActionPreference
# = Stop, so every one goes through this.
function Run { & $args[0] @($args | Select-Object -Skip 1); if ($LASTEXITCODE) { throw "failed (exit $LASTEXITCODE): $args" } }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

# LibreOffice renders the slides; ffmpeg encodes the video.
$soffice = Join-Path $env:ProgramFiles "LibreOffice\program\soffice.com"
if (-not (Test-Path $soffice)) {
    Run winget install --id TheDocumentFoundation.LibreOffice -e --accept-source-agreements --accept-package-agreements
}
if (-not (Have ffmpeg)) {
    Run winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

if (-not (Have uv)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
}
$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Run uv venv --python 3.12 (Join-Path $here ".venv") }

# torch first, from PyTorch's own index: CUDA if there's an NVIDIA GPU, CPU otherwise.
$index = "https://download.pytorch.org/whl/cpu"
if ((Have nvidia-smi) -and (nvidia-smi 2>$null)) { $index = "https://download.pytorch.org/whl/cu128" }
Run uv pip install --python $py --index-url $index torch
Run uv pip install --python $py -r (Join-Path $here "requirements.txt")

# Pre-fetch the model + default voice so the first real run doesn't stall on a download.
Run $py -c "from huggingface_hub import hf_hub_download as d; [d('hexgrad/Kokoro-82M', f) for f in ('config.json', 'kokoro-v1_0.pth', 'voices/af_heart.pt')]; print('Kokoro-82M cached.')"

if ($AddToPath) {
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($user -split ";") -notcontains $here) {
        [Environment]::SetEnvironmentVariable("Path", "$user;$here", "User")
        Write-Host "Added $here to your user PATH (open a new terminal)."
    }
}
Write-Host "OK: run  $here\deck-narrator.cmd path\to\deck.pptx"
