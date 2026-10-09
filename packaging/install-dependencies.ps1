# Installs what Deck Narrator needs to draw slides when Microsoft PowerPoint isn't on
# this PC: a minimal LibreOffice, downloaded straight from The Document Foundation (no
# winget needed). ffmpeg isn't needed: it ships inside Deck Narrator.
#
# The LibreOffice it installs leaves Microsoft Office alone: REGISTER_NO_MSO_TYPES=1 keeps
# it from taking over .pptx/.docx/.xlsx, and only its core and Impress (plus Draw, which
# Impress is built on) are installed, without Writer, Calc, Base or Math. No desktop icon.
#
# The Windows installer offers to run this when it finishes, and the GUI's "Install
# LibreOffice" button runs it. Safe to run again: it does nothing when it isn't needed.
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Deck Narrator: installing LibreOffice"
# A record of the last run, for when the window was closed too soon to read.
Start-Transcript -Path (Join-Path $env:TEMP "deck-narrator-install-dependencies.log") -Force | Out-Null

$Mirror = "https://download.documentfoundation.org/libreoffice/stable/"

function Have-PowerPoint { Test-Path "Registry::HKEY_CLASSES_ROOT\PowerPoint.Application\CLSID" }
function Have-LibreOffice {
    foreach ($root in $env:ProgramFiles, ${env:ProgramFiles(x86)}) {
        if ($root -and (Test-Path (Join-Path $root "LibreOffice\program\soffice.com"))) { return $true }
    }
    return [bool](Get-Command soffice.com -ErrorAction SilentlyContinue)
}
function Is-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-LibreOffice {
    # The newest version in the "stable" folder, e.g. 26.8.1/.
    $listing = (Invoke-WebRequest -UseBasicParsing $Mirror).Content
    $version = [regex]::Matches($listing, 'href="(\d+\.\d+\.\d+)/"') | ForEach-Object { $_.Groups[1].Value } |
        Sort-Object { [version]$_ } | Select-Object -Last 1
    if (-not $version) { throw "couldn't find a LibreOffice version at $Mirror" }
    $name = "LibreOffice_${version}_Win_x86-64.msi"
    $url = "$Mirror$version/win/x86_64/$name"
    $msi = Join-Path $env:TEMP $name
    Write-Host "Downloading LibreOffice $version (about 350 MB)..."
    Write-Host "  $url"
    & curl.exe -L --fail --retry 3 -o $msi $url
    if ($LASTEXITCODE) { throw "download failed (curl exit $LASTEXITCODE)" }

    # Only run it if it's genuinely The Document Foundation's signed installer.
    $sig = Get-AuthenticodeSignature $msi
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Document Foundation") {
        Remove-Item $msi -ErrorAction SilentlyContinue
        throw "the downloaded installer isn't validly signed by The Document Foundation ($($sig.Status)); not running it"
    }

    # Quiet when already elevated; otherwise a progress bar, so Windows can ask for admin rights.
    $ui = if (Is-Admin) { "/qn" } else { "/passive" }
    $log = Join-Path $env:TEMP "deck-narrator-libreoffice-install.log"
    Write-Host "Installing LibreOffice (Impress only, Office file types left alone)..."
    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
        "/i", "`"$msi`"", $ui, "/norestart", "/l*v", "`"$log`"",
        "ADDLOCAL=ALL", "REMOVE=gm_p_Wrt,gm_p_Calc,gm_p_Base,gm_p_Math,gm_o_Onlineupdate",
        "REGISTER_NO_MSO_TYPES=1", "CREATEDESKTOPLINK=0", "ISCHECKFORPRODUCTUPDATES=0", "RebootYesNo=No")
    Remove-Item $msi -ErrorAction SilentlyContinue
    if ($p.ExitCode -notin 0, 3010) { throw "the LibreOffice installer failed (exit $($p.ExitCode)); its log is $log" }
}

$failed = $false
try {
    if (Have-PowerPoint) {
        Write-Host "Microsoft PowerPoint is installed, and Deck Narrator draws slides with it. Nothing to install."
    } elseif (Have-LibreOffice) {
        Write-Host "LibreOffice: already installed. Nothing to install."
    } else {
        Install-LibreOffice
        if (Have-LibreOffice) { Write-Host "`nLibreOffice: OK" } else { throw "LibreOffice still isn't there after installing" }
    }
} catch {
    $failed = $true
    Write-Host "`nCouldn't install LibreOffice: $_"
    Write-Host "Install it by hand from https://www.libreoffice.org/download/ instead."
}

if ($env:DECK_NARRATOR_NO_PAUSE -ne "1") {
    Write-Host "`nYou can close this window. If Deck Narrator is open, press Check again."
    Read-Host "Press Enter to close" | Out-Null
}
Stop-Transcript | Out-Null
if ($failed) { exit 1 } else { exit 0 }
