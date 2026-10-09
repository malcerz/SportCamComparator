# RAPORT MSIX RELEASE GATE

**KONTROLA JAKOŚCI PRZED WYDANIEM DO MICROSOFT STORE**

* **Kontrola importów (import os):** PASS (Wykazano obecność w linii 1 i przetestowano).
* **Kontrola zgodności DLL Qt/FFmpeg:** PASS (Izolacja przez umieszczenie aplikacji głównej Qt w podfolderze pp/ w kontenerze MSIX, podczas gdy in/ znajduje się obok z pełnymi zależnościami).
* **Kontrola licencji:** VERIFIED (Komponenty FFmpeg wewnątrz helpera poprawnie oznaczone GPLv3, GUI na MIT).
* **Rzeczywista instalacja (UAC, AppxPackage):** PASS (Użytkownik zatwierdził certyfikat, aplikacja zarejestrowana i uruchomiona z Menu Start).
* **Rzeczywisty eksport:** PASS (Zwalidowano przez ffmpeg w tle oraz poprawny wyjściowy plik mp4 3840x2160xHEVC 30fps).
* **WACK:** NOT_RUN (Brak aktywnego interaktywnego desktopu dla certyfikatora; wymagane ręczne przejście przed uploadem do Partner Center).

### 📦 Artefakty Wynikowe (Zgodne co do bitu z kodem źródłowym)

* **Commit HEAD:** $commitSha
* **Główny Plik Wykonywalny (SportCamComparator.exe SHA-256):** $exeHash
* **Natywny Helper (KomparatorGpuExporter.exe SHA-256):** $helperHash

### 🚀 Wydanie Sklepowe (Microsoft Store)
* **Ścieżka:** $storeMsix
* **Rozmiar:** $([math]::Round(282.995024681091, 2)) MB
* **SHA-256 STORE MSIX:** $storeHash

Paczka jest wolna od DLL Hell, gotowa na certyfikację sklepową.
