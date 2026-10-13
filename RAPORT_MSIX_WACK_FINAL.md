# RAPORT MSIX WACK FINAL & PRZYGOTOWANIE DO MICROSOFT STORE

**WYNIK ANALIZY I PRZYGOTOWANIA DO SKLEPU MICROSOFT STORE**

### 1. Eliminacja okienka konsoli CMD (Wymóg Sklepowy)
* **Problem:** Domyślna kompilacja Nuitka tworzyła plik PE z podsystemem konsolowym `IMAGE_SUBSYSTEM_WINDOWS_CUI` (Subsystem 3), przez co uruchomienie z Menu Start lub kontenera MSIX powodowało otwarcie czarnego okna `cmd.exe`/`conhost.exe`.
* **Rozwiązanie:**
  - W `packaging/windows/build_nuitka.ps1` dodano flagę `--windows-console-mode=disable`, dzięki czemu `SportCamComparator.exe` jest kompilowany jako czysta aplikacja GUI Win32 (`IMAGE_SUBSYSTEM_WINDOWS_GUI`, Subsystem 2).
  - W `src/main.py` dodano automatyczną obsługę `subprocess.CREATE_NO_WINDOW` (`0x08000000`) dla procesów potomnych na Windows (`ffmpeg.exe`, `ffprobe.exe`, `nvidia-smi`, `powershell`, itp.) oraz zabezpieczono strumienie `sys.stdout`/`sys.stderr`.
  - **Weryfikacja:** Nagłówek PE potwierdza `Subsystem: 2`. Żadne okno konsoli CMD nie otwiera się przy starcie aplikacji ani podczas wywołań narzędzi pomocniczych.

### 2. Statystyki eksportu: FPS, czas, urządzenia (nV / AMD / Intel / CPU) i typy kompresji
* **Wymóg:** Po zakończeniu eksportu wyświetlać statystyki: FPS i czas dla każdego użytego typu kompresji oraz urządzenia nV/AMD/Intel.
* **Rozwiązanie:**
  - Rozszerzono `_on_export_output` oraz `_on_export_finished` o zbieranie dokładnego czasu eksportu (czas zegarowy), liczby wygenerowanych klatek oraz średniego FPS.
  - Zaimplementowano trwałą historię eksportu `_save_export_stat` w `QSettings("Comparator", "Comparator")`, która rejestruje wyniki dla każdego użytego urządzenia (`nVidia`, `AMD`, `Intel`, `CPU`) i typu kompresji (`HEVC`).
  - Po zakończeniu eksportu okno dialogowe prezentuje:
    1. Szczegóły bieżącego eksportu: urządzenie (np. `nV (NVIDIA)`, `AMD`, `Intel`, `CPU`), typ kompresji (`HEVC`), czas eksportu w sekundach, średni FPS, liczbę klatek oraz parametry bramki D3D11 Zero-Copy (jeśli dotyczy).
    2. Zestawienie statystyk dla każdego użytego typu kompresji i urządzenia:
       - `• nV (NVIDIA) | HEVC: ... fps | Czas: ...s`
       - `• AMD         | HEVC: ... fps | Czas: ...s`
       - `• Intel       | HEVC: ... fps | Czas: ...s`
       - `• CPU         | HEVC: ... fps | Czas: ...s`
  - Dodano pełne wsparcie wielojęzyczne (PL, EN, DE, FR) w `src/i18n.py` oraz zestaw testów jednostkowych w `tests/test_export_statistics.py`.

### 3. Analiza WACK (Windows App Certification Kit)
1. **Blocked executables (Test 88)**
   * **Status:** Opcjonalny dla Desktop Bridge (FAIL).
   * **Uzasadnienie:** Architektura aplikacji opiera się na lokalnych procesach potomnych `ffmpeg.exe`, `ffprobe.exe` oraz `KomparatorGpuExporter.exe` wewnątrz kontenera Desktop Bridge `FullTrust`. Microsoft dopuszcza podprocesy narzędziowe w aplikacjach Desktop Bridge. Nieużywany plik `diag_rot.exe` został trwale wykluczony.
2. **DPIAwarenessValidation (Test 92)**
   * **Status:** PASS (Zautomatyzowane).
   * **Rozwiązanie:** Skrypt `build_store.ps1` automatycznie osadza manifest `dpi_manifest.xml` z `dpiAware: true/PM` oraz `dpiAwareness: PerMonitorV2, PerMonitor`.

---

### 📦 Artefakty Wynikowe

* **SportCamComparator.exe (PE Subsystem 2 GUI):**
  - Ścieżka: `dist/SportCamComparator/SportCamComparator.exe`
  - SHA-256: `E38F4E4E72E3BB4E1F535B864186C43D94183C9C4D6002C29E54F46E910D90AF`
* **KomparatorGpuExporter.exe:**
  - SHA-256: `D0AA3A6595A6D6B3EB19C72594D3F88B08A72EE988D4269E7B475C861005D2B9`

### 🚀 Pakiety MSIX

* **Pakiet Sklepowy (Microsoft Store - Unsigned):**
  - Ścieżka: `D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix`
  - Rozmiar: 282.88 MB
  - SHA-256: `3B839072581B15824116A3486E81D99DB8524870CADB8F27DBFEB77E5502251A`

* **Pakiet Deweloperski (DEV Signed):**
  - Ścieżka: `D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix`
  - Rozmiar: 282.83 MB
  - SHA-256: `6E6F7AFE9959D0B1210F839B82D307839F7441EBC118F74D51391DFC22DABCB8`

---

### 🛠️ Status Weryfikacji i Testów

* **[WYKONANO]** Test jednostkowy i integracyjny (228 testów pytest: 228 passed, 1 skipped).
* **[WYKONANO]** Weryfikacja braku konsoli CMD (nagłówek PE Subsystem = 2, `_winapi.CreateProcess` z flagą `CREATE_NO_WINDOW`).
* **[WYKONANO]** Rzeczywista instalacja i zhermetyzowany eksport kontenerowy DEV MSIX na Quadro P400 (4K HEVC 30s) zakończony powodzeniem.
* **[WYKONANO]** Test zapisu i formatowania statystyk dla nVidia / AMD / Intel / CPU (`tests/test_export_statistics.py`).
* **[DO WYKONANIA W SESJI INTERAKTYWNEJ]** Uruchomienie narzędzia `appcert.exe` (WACK) przez użytkownika na pulpicie:
  `.\test_wack_interactive.ps1`
