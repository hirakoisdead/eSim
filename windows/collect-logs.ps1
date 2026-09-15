<#
=============================================================================
          FILE: collect-logs.ps1

         USAGE: powershell -ExecutionPolicy Bypass -File windows\collect-logs.ps1
                (run it from the eSim INSTALL dir, e.g. C:\FOSSEE\eSim, or
                 from a repo checkout on the build machine)

   DESCRIPTION: Debugging companion for the Windows shakedown loop: bundles
                everything a developer needs to diagnose a broken install
                into ONE zip on the Desktop, so a user can attach/paste it
                without hunting through hidden folders:

                  * the toolchain doctor report (esim --doctor)
                  * %USERPROFILE%\.esim   (config, dcosim.log, symbols)
                  * %USERPROFILE%\.nghdl  (toolchain config)
                  * spinit + the code-model inventory of the bundled ngspice
                  * pip wheel lock + VERSION/RELEASE stamps
                  * build logs (windows\build\*.log) when run from a repo

  ORGANIZATION: eSim Team, FOSSEE, IIT Bombay
=============================================================================
#>
$ErrorActionPreference = 'Continue'   # collect what exists, skip what doesn't

$Root  = Split-Path $PSScriptRoot -Parent      # install root or repo root
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Work  = Join-Path $env:TEMP "esim-logs-$Stamp"
$Zip   = Join-Path ([Environment]::GetFolderPath('Desktop')) "esim-logs-$Stamp.zip"
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Grab([string]$src, [string]$name) {
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $Work $name) -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host ">>> collected $src"
    } else {
        Write-Host ">>> absent    $src"
    }
}

# Doctor report (the headline diagnostic).
$py = Join-Path $Root 'python\python.exe'
$app = Join-Path $Root 'src\frontEnd\Application.py'
if ((Test-Path $py) -and (Test-Path $app)) {
    & $py $app --doctor 2>&1 | Set-Content (Join-Path $Work 'doctor-report.txt')
    Write-Host '>>> collected doctor report'
}

# Per-user state.
Grab (Join-Path $env:USERPROFILE '.esim')  'dot-esim'
Grab (Join-Path $env:USERPROFILE '.nghdl') 'dot-nghdl'

# Bundled ngspice state: spinit (rewritten by the bootstrap) + .cm inventory.
$inst = Join-Path $Root 'tools\nghdl\install_dir'
Grab (Join-Path $inst 'share\ngspice\scripts\spinit') 'spinit.txt'
if (Test-Path (Join-Path $inst 'lib\ngspice')) {
    Get-ChildItem (Join-Path $inst 'lib\ngspice') |
        Select-Object Name, Length |
        Format-Table | Out-String |
        Set-Content (Join-Path $Work 'codemodels.txt')
}

# Install/build metadata.
Grab (Join-Path $Root 'VERSION')            'VERSION.txt'
Grab (Join-Path $Root 'RELEASE')            'RELEASE.txt'
Grab (Join-Path $Root 'python-wheels.lock') 'python-wheels.lock'
Get-ChildItem (Join-Path $PSScriptRoot 'build') -Filter '*.log' -ErrorAction SilentlyContinue |
    ForEach-Object { Grab $_.FullName $_.Name }

# System context that regularly explains Windows-only failures.
@(
    "windows : $([Environment]::OSVersion.VersionString)"
    "user    : $env:USERNAME  (profile: $env:USERPROFILE)"
    "root    : $Root"
    "PATH    : $env:PATH"
) | Set-Content (Join-Path $Work 'system-info.txt')

Compress-Archive -Path "$Work\*" -DestinationPath $Zip -Force
Remove-Item $Work -Recurse -Force
Write-Host ""
Write-Host ">>> Done. Send this file: $Zip" -ForegroundColor Cyan
