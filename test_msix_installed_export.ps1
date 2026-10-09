# Reinstall DEV MSIX
Write-Host "Reinstalling MSIX..."
$pkg = "Malcerz.SportCamComparator_1.0.0.0_x64__qd1bkbsbzd9mc"
Remove-AppxPackage -Package $pkg -ErrorAction SilentlyContinue
Add-AppxPackage -Path "D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix"

# Run actual export via Invoke-CommandInDesktopPackage
Write-Host "Running export inside MSIX container..."
$outDir = "$env:LOCALAPPDATA\Packages\Malcerz.SportCamComparator_qd1bkbsbzd9mc\LocalState"
$projectDir = "D:\GoPro\SportCamComparator"

# Clean old logs
Remove-Item "$outDir\export_log.txt" -ErrorAction SilentlyContinue
Remove-Item "$projectDir\tests\artifacts\export_output_msix.mp4" -ErrorAction SilentlyContinue

# Execute export
$cmdArgs = "--config ""$projectDir\tests\artifacts\export_4k_test.json"""
Invoke-CommandInDesktopPackage -AppId SportCamComparator -PackageFamilyName Malcerz.SportCamComparator_qd1bkbsbzd9mc -Command "cmd.exe" -Args "/c app\bin\KomparatorGpuExporter.exe $cmdArgs > ""$outDir\export_log.txt"" 2>&1"

Start-Sleep -Seconds 12

# Probe result
Write-Host "Probing result..."
& "D:\GoPro\SportCamComparator\bin\ffprobe.exe" -v error -show_entries stream=codec_name,width,height,avg_frame_rate,duration -of default=noprint_wrappers=1 "$projectDir\tests\artifacts\export_4k_test.mp4"
