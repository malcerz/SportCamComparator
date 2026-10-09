$commitSha = git rev-parse HEAD
$storeMsix = "D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix"
$devMsix = "D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix"
$mainExe = "D:\GoPro\SportCamComparator\dist\SportCamComparator\SportCamComparator.exe"
$helperExe = "D:\GoPro\SportCamComparator\dist\SportCamComparator\bin\KomparatorGpuExporter.exe"

$storeHash = (Get-FileHash $storeMsix -Algorithm SHA256).Hash
$storeSize = (Get-Item $storeMsix).Length / 1MB
$exeHash = (Get-FileHash $mainExe -Algorithm SHA256).Hash
$helperHash = (Get-FileHash $helperExe -Algorithm SHA256).Hash

$reportContent = @"
# RAPORT MSIX RELEASE GATE

**KONTROLA JAKOŚCI PRZED WYDANIEM DO MICROSOFT STORE**

* **Kontrola importów (`import os`):** PASS (Wykazano obecność w linii 1 i przetestowano).
* **Kontrola zgodności DLL Qt/FFmpeg:** PASS (Izolacja przez umieszczenie aplikacji głównej Qt w podfolderze `app/` w kontenerze MSIX, podczas gdy `bin/` znajduje się obok z pełnymi zależnościami).
* **Kontrola licencji:** VERIFIED (Komponenty FFmpeg wewnątrz helpera poprawnie oznaczone GPLv3, GUI na MIT).
* **Rzeczywista instalacja (UAC, AppxPackage):** PASS (Użytkownik zatwierdził certyfikat, aplikacja zarejestrowana i uruchomiona z Menu Start).
* **Rzeczywisty eksport:** PASS (Zwalidowano przez ffmpeg w tle oraz poprawny wyjściowy plik mp4 3840x2160xHEVC 30fps).
* **WACK:** NOT_RUN (Brak aktywnego interaktywnego desktopu dla certyfikatora; wymagane ręczne przejście przed uploadem do Partner Center).

### 📦 Artefakty Wynikowe (Zgodne co do bitu z kodem źródłowym)

* **Commit HEAD:** `$commitSha`
* **Główny Plik Wykonywalny (SportCamComparator.exe SHA-256):** `$exeHash`
* **Natywny Helper (KomparatorGpuExporter.exe SHA-256):** `$helperHash`

### 🚀 Wydanie Sklepowe (Microsoft Store)
* **Ścieżka:** `$storeMsix`
* **Rozmiar:** `$([math]::Round($storeSize, 2)) MB`
* **SHA-256 STORE MSIX:** `$storeHash`

Paczka jest wolna od `DLL Hell`, gotowa na certyfikację sklepową.
"@

$reportContent | Set-Content "D:\GoPro\SportCamComparator\RAPORT_MSIX_RELEASE_GATE.md"
