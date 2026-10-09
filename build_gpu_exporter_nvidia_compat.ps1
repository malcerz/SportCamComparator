# Build / deploy script for Komparator GPU Exporter NVIDIA Compat
[CmdletBinding()]
param(
    [string]$Configuration = "Release",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Building KomparatorGpuExporterNvidia ($Configuration) " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Run main build script
$MainBuildScript = Join-Path $ScriptDir "build_gpu_exporter.ps1"
if (-not (Test-Path $MainBuildScript)) {
    throw "Main build script not found: $MainBuildScript"
}

if ($Clean) {
    & $MainBuildScript -Configuration $Configuration -Clean
} else {
    & $MainBuildScript -Configuration $Configuration
}
if ($LASTEXITCODE -ne 0) {
    throw "Underlying build failed with code $LASTEXITCODE"
}

# 2. Deploy KomparatorGpuExporterNvidia.exe to bin/
$SrcExe = Join-Path $ScriptDir "bin\KomparatorGpuExporter.exe"
$DstExe = Join-Path $ScriptDir "bin\KomparatorGpuExporterNvidia.exe"

if (-not (Test-Path $SrcExe)) {
    throw "Source executable not found: $SrcExe"
}

Copy-Item -LiteralPath $SrcExe -Destination $DstExe -Force
if (-not (Test-Path $DstExe)) {
    throw "Failed to create target NVIDIA compat executable: $DstExe"
}

Write-Host "==================================================" -ForegroundColor Green
Write-Host " SUCCESS! Built NVIDIA compat helper: $DstExe" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
