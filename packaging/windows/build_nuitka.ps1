$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Set-Location $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Building SportCamComparator with Nuitka " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Ensure Nuitka is available
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    throw "Python not found in PATH"
}

Write-Host "Executing Nuitka build..."
python -m nuitka `
    --standalone `
    --enable-plugin=pyside6 `
    --include-qt-plugins=qml,multimedia `
    --include-data-dir="src=src" `
    --include-data-dir="assets=assets" `
    --include-data-dir="bin=bin" `
    --windows-icon-from-ico="assets/app.ico" `
    --company-name="Malcerz" `
    --product-name="SportCamComparator" `
    --file-version="1.0.0.0" `
    --product-version="1.0.0.0" `
    --output-dir="dist" `
    src/main.py

if ($LASTEXITCODE -ne 0) {
    throw "Nuitka build failed."
}

# Rename the executable for clarity if necessary
$ExePath = Join-Path "dist" "main.dist\main.exe"
$NewExePath = Join-Path "dist" "main.dist\SportCamComparator.exe"
if (Test-Path $ExePath) {
    Rename-Item $ExePath "SportCamComparator.exe"
}

# Rename dist folder
$OldDist = Join-Path "dist" "main.dist"
$NewDist = Join-Path "dist" "SportCamComparator"
if (Test-Path $OldDist) {
    if (Test-Path $NewDist) {
        Remove-Item -Recurse -Force $NewDist
    }
    Rename-Item $OldDist "SportCamComparator"
}

# Clean up unwanted test files from bin if they exist in dist
$DistBin = Join-Path $NewDist "bin"
if (Test-Path $DistBin) {
    Remove-Item -Path (Join-Path $DistBin "*.json") -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $DistBin "*.png") -ErrorAction SilentlyContinue
    # ffplay.exe might be quite large, could remove to save space
    Remove-Item -Path (Join-Path $DistBin "ffplay.exe") -ErrorAction SilentlyContinue
}

Write-Host "==================================================" -ForegroundColor Green
Write-Host " SUCCESS! Built: $NewDist\SportCamComparator.exe" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
