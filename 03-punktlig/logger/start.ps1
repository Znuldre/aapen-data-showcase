<#
Starter Punktlig-loggeren i bakgrunnen, uten konsollvindu og med lav prioritet.
Prosessen lever videre når terminalen lukkes, men ikke over en omstart av maskinen.

    powershell -ExecutionPolicy Bypass -File 03-punktlig\logger\start.ps1
#>
$ErrorActionPreference = "Stop"
$logger = Split-Path -Parent $MyInvocation.MyCommand.Path
$rot = (Resolve-Path (Join-Path $logger "..\..")).Path
$data = Join-Path (Split-Path -Parent $logger) "data"
$pidfil = Join-Path $data "logger.pid"
$python = Join-Path $rot ".venv\Scripts\python.exe"
$skript = Join-Path $logger "logger.py"

function Kjorer {
    if (-not (Test-Path $pidfil)) { return $null }
    $id = Get-Content $pidfil -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $id) { return $null }
    $p = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") { return $p }
    return $null
}

if (-not (Test-Path $python)) {
    Write-Host "Fant ikke $python - lag Python-miljøet først (se README i prosjektroten)."
    exit 1
}
$p = Kjorer
if ($p) {
    Write-Host "Loggeren kjører allerede (pid $($p.Id))."
    exit 0
}
Remove-Item $pidfil -ErrorAction SilentlyContinue

# python.exe i et skjult konsollvindu: pythonw.exe fra uv krasjer eller henger under import av
# numpy (testet oktober 2026). .venv\Scripts\python.exe er en liten starter som åpner selve
# tolkeren som egen prosess, så loggeren skriver sin egen pid til data\logger.pid.
Start-Process -FilePath $python -ArgumentList @("-I", "`"$skript`"") -WorkingDirectory $rot -WindowStyle Hidden
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    $p = Kjorer
    if ($p) {
        Write-Host "Loggeren kjører i bakgrunnen (pid $($p.Id)). Logg: $data\logger.log"
        Write-Host "Stopp den med stopp.ps1. Status og punktlighet: kontroll.py"
        exit 0
    }
}
Write-Host "Loggeren meldte seg ikke innen 90 s - se $data\logger.log"
exit 1
