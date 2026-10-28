<#
Stopper Punktlig-loggeren pent: lager stoppfilen, og loggeren lagrer det som er avklart,
slår sammen staging til daglige filer og avslutter. Svarer den ikke innen 3 min, avsluttes den.

    powershell -ExecutionPolicy Bypass -File 03-punktlig\logger\stopp.ps1
#>
$ErrorActionPreference = "Stop"
$logger = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = Join-Path (Split-Path -Parent $logger) "data"
$pidfil = Join-Path $data "logger.pid"
$stoppfil = Join-Path $data "logger.stopp"

if (-not (Test-Path $pidfil)) {
    Write-Host "Loggeren kjører ikke (fant ingen pid-fil)."
    exit 0
}
$id = [int](Get-Content $pidfil | Select-Object -First 1)
$p = Get-Process -Id $id -ErrorAction SilentlyContinue
if (-not $p -or $p.ProcessName -notlike "python*") {
    Write-Host "Loggeren kjører ikke (pid $id finnes ikke)."
    Remove-Item $pidfil -ErrorAction SilentlyContinue
    exit 0
}
Set-Content -Path $stoppfil -Value "stopp" -Encoding ascii
Write-Host "Ber loggeren avslutte pent (lagrer og slår sammen data) ..."
if ($p.WaitForExit(180000)) {
    Write-Host "Loggeren er stoppet."
} else {
    Stop-Process -Id $id -Force
    Remove-Item $stoppfil -ErrorAction SilentlyContinue
    Write-Host "Loggeren svarte ikke innen 3 min og ble avsluttet. Staging-filer slås sammen ved neste start."
}
