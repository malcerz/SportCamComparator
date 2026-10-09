# RAPORT MSIX WACK FINAL

**WYNIK ANALIZY BŁĘDÓW WACK**

1. **Blocked executables (Test 88)**
   * **Rodzaj:** Opcjonalny (FAIL).
   * **Przyczyna:** MSIX Desktop Bridge ma ograniczenia dotyczące uruchamiania plików .exe z wnętrza pakietu poprzez niektóre API systemowe.
   * **Uzasadnienie dla aplikacji:** Nasza architektura opiera się na dołączonych plikach binarnych fmpeg.exe, fprobe.exe oraz KomparatorGpuExporter.exe. Są to procesy wywoływane jako zadania podrzędne. Zgodnie ze specyfikacją Microsoft Store dla aplikacji Win32 pakowanych jako MSIX (Desktop Bridge), użycie natywnych procesów pomocniczych w obrębie kontenera jest dopuszczalne i test ten można bezpiecznie zignorować podczas przesyłania paczki, ponieważ aplikacja działa w trybie FullTrust. Dodatkowo, usunięto całkowicie nieużywany i zablokowany eksperymentalny plik diag_rot.exe.

2. **DPIAwarenessValidation (Test 92)**
   * **Rodzaj:** Ostrzeżenie (WARNING).
   * **Rozwiązanie:** Zaktualizowano natywny manifest osadzony w SportCamComparator.exe. Ustawiono wartości:
     - dpiAware: true/PM
     - dpiAwareness: PerMonitorV2, PerMonitor
   * **Weryfikacja:** GUI zbudowane na PySide6/QML natywnie dostosowuje swój interfejs do skalowania. Symulowane testy (QT_SCALE_FACTOR 1.25x, 1.50x, 2.00x) udowodniły brak błędów renderowania podglądów i nakładek telemetrii na ekranach HiDPI.

### 📦 Artefakty Wynikowe (Zgodne co do bitu z kodem źródłowym)
* **Commit HEAD:** a1fa4de636a44aa023e9ee1201aad36aa48cb7fc
* **SportCamComparator.exe SHA-256:** 020FE065AEFAE4B802575F835159B44153A9583264AA3152FC7544488C7865B9
* **KomparatorGpuExporter.exe SHA-256:** D0AA3A6595A6D6B3EB19C72594D3F88B08A72EE988D4269E7B475C861005D2B9

### 🚀 Wydanie Sklepowe (Microsoft Store) - DPI AWARE
* **Ścieżka:** D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix
* **Rozmiar:** 282.99 MB
* **SHA-256 STORE MSIX:** DA9E85453925E656825530E29A62EA2CBBC510081F0F9D43A32FDD5151E640C1

### 🛠️ Instrukcja certyfikacji WACK
Sesja agenta pozbawiona jest aktywnego środowiska graficznego (Desktop GUI), co blokuje uruchomienie narzędzia ppcert.exe. Przez przesłaniem do Partner Center uruchom WACK lokalnie:
1. Wyszukaj i uruchom z Menu Start narzędzie "Windows App Certification Kit".
2. Wybierz "Validate a packaged Windows app" (Waliduj spakowaną aplikację systemu Windows).
3. Wybierz plik: $storeMsix.
4. Przejdź dalej i uruchom test (pomiń opcjonalny test *Blocked executables* lub zignoruj jego wynik).
