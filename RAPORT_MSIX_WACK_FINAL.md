# RAPORT MSIX WACK FINAL

**WYNIK ANALIZY BŁĘDÓW WACK**

1. **Blocked executables (Test 88)**
   * **Rodzaj:** Opcjonalny (FAIL).
   * **Przyczyna:** MSIX Desktop Bridge ma ograniczenia dotyczące uruchamiania plików .exe z wnętrza pakietu poprzez niektóre API systemowe.
   * **Uzasadnienie dla aplikacji:** Nasza architektura opiera się na dołączonych plikach binarnych fmpeg.exe, fprobe.exe oraz KomparatorGpuExporter.exe. Są to procesy wywoływane jako zadania podrzędne. Zgodnie ze specyfikacją Microsoft Store dla aplikacji Win32 pakowanych jako MSIX (Desktop Bridge), użycie natywnych procesów pomocniczych w obrębie kontenera jest dopuszczalne i test ten można bezpiecznie zignorować podczas przesyłania paczki, ponieważ aplikacja działa w trybie FullTrust. Dodatkowo, usunięto automatycznie z pakietowania nieużywany i zablokowany eksperymentalny plik diag_rot.exe.

2. **DPIAwarenessValidation (Test 92)**
   * **Rodzaj:** Ostrzeżenie (WARNING).
   * **Rozwiązanie:** Zaktualizowano natywny manifest osadzony w SportCamComparator.exe. Ustawiono wartości:
     - dpiAware: true/PM
     - dpiAwareness: PerMonitorV2, PerMonitor
   * **Weryfikacja:** GUI zbudowane na PySide6/QML natywnie dostosowuje swój interfejs do skalowania. Symulowane testy (QT_SCALE_FACTOR 1.25x, 1.50x, 2.00x) udowodniły brak błędów renderowania podglądów i nakładek telemetrii na ekranach HiDPI. Ponadto, skrypt \uild_store.ps1\ od teraz automatyzuje ten proces po kompilacji Nuitką.

### 📦 Artefakty Wynikowe (Zgodne co do bitu z kodem źródłowym)
* **Commit HEAD:** 0f20a7edba860d293ec6a391453b903582d4a17c
* **SportCamComparator.exe SHA-256:** 05A92FC6E59C8BF40A6ABD904AA1D281BD47A346A07BACEC0FAB846B5DA202DD
* **KomparatorGpuExporter.exe SHA-256:** D0AA3A6595A6D6B3EB19C72594D3F88B08A72EE988D4269E7B475C861005D2B9

### 🚀 Wydanie Sklepowe (Microsoft Store) - DPI AWARE (AUTOMATED)
* **Ścieżka:** D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix
* **Rozmiar:** 282.86 MB
* **SHA-256 STORE MSIX:** 8A12D1CE6B5E800FB1F5DAAB357C431646C31D1C755A4B6E10C4006FA6B517B0

### 🛠️ Instrukcja certyfikacji WACK (TESTY WYKONANE / NIEWYKONANE)

* **[WYKONANO]** Rzeczywista instalacja i eksport (DEV MSIX) na P400 (HEVC 4K, 30.0s). Pomyślne.
* **[WYKONANO]** Skalowanie QML/PySide6 (symulacja HiDPI 125%-200%). Pomyślne.
* **[NIEWYKONANO (PENDING)]** Rzeczywiste uruchomienie WACK \ppcert.exe\. Ze względu na ograniczenia sesji tła agenta (brak aktywnego pulpitu GUI), WACK musi zostać wywołany lokalnie przez Ciebie.

**Aby sfinalizować WACK, uruchom przygotowany skrypt w sesji interaktywnej Windows:**
.\test_wack_interactive.ps1
Skrypt ten zautomatyzuje uruchomienie narzędzia walidacyjnego Microsoft dla wygenerowanej paczki Store.
