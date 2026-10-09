$ErrorActionPreference = "Stop"

Write-Host "Installing Dev MSIX package..."
Add-AppxPackage -Path "dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix"

Write-Host "Getting package info..."
$Package = Get-AppxPackage -Name "Malcerz.SportCamComparator"
Write-Host "PackageFullName: $($Package.PackageFullName)"
Write-Host "InstallLocation: $($Package.InstallLocation)"

Write-Host "Starting GUI from Start Menu..."
Start-Process "shell:AppsFolder\$($Package.PackageFamilyName)!SportCamComparator"
Start-Sleep -Seconds 5
$Proc = Get-Process SportCamComparator -ErrorAction SilentlyContinue
if ($Proc) {
    Write-Host "GUI started successfully. Process ID: $($Proc.Id)"
    Stop-Process -Id $Proc.Id -Force
} else {
    Write-Host "GUI failed to start."
}

Write-Host "Running 4K HEVC export natively from installed app..."
$ExporterPath = Join-Path $Package.InstallLocation "bin\KomparatorGpuExporter.exe"
& $ExporterPath --config tests\artifacts\export_4k_test.json
