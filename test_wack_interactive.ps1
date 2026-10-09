$msixPath = "D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix"
$reportOut = "D:\GoPro\SportCamComparator\wack_report.xml"

Write-Host "Rozpoczynanie certyfikacji WACK (Windows App Certification Kit)..." -ForegroundColor Cyan
Write-Host "Pamiętaj, że ten test WYMAGA aktywnego pulpitu (interaktywnej sesji)!" -ForegroundColor Yellow

# Locate appcert.exe
$appcert = (Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\App Certification Kit" -Filter appcert.exe -Recurse | Select-Object -First 1).FullName

if (-not $appcert) {
    Write-Error "Nie znaleziono appcert.exe. Zainstaluj Windows SDK z opcją WACK."
    exit 1
}

& $appcert test -apptype desktopbridge -packagefullname "Malcerz.SportCamComparator_1.0.0.0_x64__qd1bkbsbzd9mc" -reportoutputpath $reportOut
# Note: For Store MSIX, it's better to test the .msix file directly:
# & $appcert test -apptype desktopbridge -packagefilepath $msixPath -reportoutputpath $reportOut

Write-Host "Test uruchomiony. Sprawdź okno WACK na pulpicie." -ForegroundColor Green
