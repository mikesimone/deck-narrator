# Builds the winget manifests and the Chocolatey package for a published release, and
# submits them when the tokens are there:
#   WINGET_TOKEN    a GitHub token (classic, public_repo) that can open pull requests on
#                   microsoft/winget-pkgs; wingetcreate forks it into that account.
#   CHOCO_API_KEY   the API key of the Chocolatey community account that owns the package.
# Without a token that half is built and checked but not sent. Run by CI (ci.yml after a
# release, and packages.yml by hand):
#   .\packaging\publish-packages.ps1 -Version 1.2.5 [-Msi path] [-TestInstall] [-Submit]
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$Msi,              # the release's MSI, if it's already here (else it's downloaded)
    [switch]$TestInstall,      # install and uninstall the Chocolatey package on this machine
    [switch]$Submit            # send to winget and Chocolatey (each only if its token is set)
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$out = Join-Path ($env:RUNNER_TEMP ?? $env:TEMP) "deck-narrator-packages"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\winget", "$out\choco\tools" | Out-Null

$url = "https://github.com/mikesimone/deck-narrator/releases/download/v$Version/deck-narrator-$Version-x64.msi"
if (-not $Msi) {
    $Msi = Join-Path $out "deck-narrator-$Version-x64.msi"
    Write-Host "Downloading $url"
    & curl.exe -L --fail --retry 3 -s -o $Msi $url
    if ($LASTEXITCODE) { throw "couldn't download $url (is v$Version released?)" }
}
$sha = (Get-FileHash $Msi -Algorithm SHA256).Hash.ToLower()

# The MSI's ProductCode (WiX makes a new one per build), from its Property table.
$wi = New-Object -ComObject WindowsInstaller.Installer
$db = $wi.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $wi, @((Resolve-Path $Msi).Path, 0))
$view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @("SELECT Value FROM Property WHERE Property='ProductCode'"))
$view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
$rec = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
$productCode = $rec.GetType().InvokeMember("StringData", "GetProperty", $null, $rec, 1)
$view.GetType().InvokeMember("Close", "InvokeMethod", $null, $view, $null) | Out-Null
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($db)
if ($productCode -notmatch '^\{[0-9A-F-]{36}\}$') { throw "unexpected ProductCode: $productCode" }
Write-Host "v$Version  sha256 $sha  ProductCode $productCode"

function Fill([string]$text) {
    $text.Replace("__VERSION__", $Version).Replace("__URL__", $url).Replace("__SHA256__", $sha).
        Replace("__PRODUCTCODE__", $productCode).Replace("__DATE__", (Get-Date -Format "yyyy-MM-dd"))
}

# winget: the three manifests, without our template comments.
foreach ($f in Get-ChildItem "$here\winget\*.yaml") {
    $lines = (Fill (Get-Content $f -Raw)) -split "`r?`n" | Where-Object { $_ -notmatch '^#' }
    [IO.File]::WriteAllText("$out\winget\$($f.Name)", (($lines -join "`n").TrimEnd() + "`n"))
}
if (Select-String -Path "$out\winget\*.yaml" -Pattern "__[A-Z0-9]+__" -Quiet) { throw "a winget placeholder wasn't filled in" }

# Chocolatey: fill in, pack.
[IO.File]::WriteAllText("$out\choco\deck-narrator.nuspec", (Fill (Get-Content "$here\chocolatey\deck-narrator.nuspec" -Raw)))
[IO.File]::WriteAllText("$out\choco\tools\chocolateyinstall.ps1", (Fill (Get-Content "$here\chocolatey\tools\chocolateyinstall.ps1" -Raw)))
if (Select-String -Path "$out\choco\deck-narrator.nuspec", "$out\choco\tools\*.ps1" -Pattern "__[A-Z0-9]+__" -Quiet) { throw "a Chocolatey placeholder wasn't filled in" }
& choco pack "$out\choco\deck-narrator.nuspec" --outputdirectory $out --limit-output
if ($LASTEXITCODE) { throw "choco pack failed" }
$nupkg = Join-Path $out "deck-narrator.$Version.nupkg"

if ($TestInstall) {
    # Exactly what a user's "choco install deck-narrator" does, from this package.
    & choco install deck-narrator --source $out --version $Version -y --no-progress --limit-output
    if ($LASTEXITCODE) { throw "choco install failed: $LASTEXITCODE" }
    $exe = "$env:ProgramFiles\Deck Narrator\deck-narrator.exe"
    if (-not (Test-Path $exe)) { throw "choco install didn't install $exe" }
    $v = & $exe --version
    if ("$v" -notmatch [regex]::Escape($Version)) { throw "installed version is '$v', not $Version" }
    & choco uninstall deck-narrator -y --no-progress --limit-output
    if ($LASTEXITCODE) { throw "choco uninstall failed: $LASTEXITCODE" }
    if (Test-Path $exe) { throw "choco uninstall left $exe behind" }
    Write-Host "Chocolatey: installed $v and uninstalled cleanly"
}

if ($Submit) {
    if ($env:WINGET_TOKEN) {
        $wc = Join-Path $out "wingetcreate.exe"
        & curl.exe -L --fail --retry 3 -s -o $wc "https://aka.ms/wingetcreate/latest"
        if ($LASTEXITCODE) { throw "couldn't download wingetcreate" }
        $env:WINGET_CREATE_GITHUB_TOKEN = $env:WINGET_TOKEN     # read from the environment, so it's never on a command line
        & $wc submit --prtitle "New version: MikeSimone.DeckNarrator version $Version" "$out\winget"
        if ($LASTEXITCODE) { throw "wingetcreate submit failed: $LASTEXITCODE" }
    } else { Write-Host "winget: built, not submitted (no WINGET_TOKEN)" }
    if ($env:CHOCO_API_KEY) {
        & choco push $nupkg --source "https://push.chocolatey.org/" --api-key $env:CHOCO_API_KEY --limit-output
        if ($LASTEXITCODE) { throw "choco push failed: $LASTEXITCODE" }
    } else { Write-Host "Chocolatey: built, not pushed (no CHOCO_API_KEY)" }
}
Get-ChildItem "$out\winget" | ForEach-Object { Write-Host "--- $($_.Name)"; Get-Content $_.FullName | Write-Host }
