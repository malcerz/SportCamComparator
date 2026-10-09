$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Set-Location $ProjectRoot

$ExePath = "dist\SportCamComparator\SportCamComparator.exe"
if (-not (Test-Path $ExePath)) {
    throw "Executable not found: $ExePath"
}

Write-Host "Running smoke test on $ExePath..."
# We run the exe and close it if it opens successfully, or we can use a command line argument if the app supports it.
# The app probably just opens the UI. We can start it and wait a bit, then kill it.
$process = Start-Process -FilePath $ExePath -PassThru

# Wait 5 seconds to see if it crashes
Start-Sleep -Seconds 5

if ($process.HasExited) {
    if ($process.ExitCode -ne 0) {
        throw "Smoke test failed! Application crashed with exit code $($process.ExitCode)."
    } else {
        Write-Host "Application exited with 0. Smoke test passed."
    }
} else {
    Write-Host "Application is still running. Smoke test passed. Terminating..."
    Stop-Process -Id $process.Id -Force
}
