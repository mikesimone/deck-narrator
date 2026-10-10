# Downloads Deck Narrator's installer from its GitHub release, checks it against the
# checksum below and installs it silently. Uninstalling goes through Windows' own
# uninstall entry (Chocolatey's auto uninstaller).
$ErrorActionPreference = 'Stop'

$packageArgs = @{
  packageName    = $env:ChocolateyPackageName
  fileType       = 'msi'
  url64bit       = '__URL__'
  checksum64     = '__SHA256__'
  checksumType64 = 'sha256'
  softwareName   = 'Deck Narrator*'
  silentArgs     = "/qn /norestart /l*v `"$($env:TEMP)\$($env:ChocolateyPackageName).$($env:ChocolateyPackageVersion).MsiInstall.log`""
  validExitCodes = @(0, 3010, 1641)
}

Install-ChocolateyPackage @packageArgs
