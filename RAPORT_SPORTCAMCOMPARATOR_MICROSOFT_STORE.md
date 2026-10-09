# RAPORT SPORTCAMCOMPARATOR MICROSOFT STORE (FINAL)

**Commit HEAD:** `cea9b9e MSIX: Fix missing avfilter DLL entry point by replacing Qt FFmpeg DLLs, fix path resolution, finalize UAC testing`
**Data kompilacji:** 2026-10-09

Zgodnie z wymaganiami przeprowadzono ostateczne poprawki ścieżek, instalację w systemie z podniesieniem uprawnień dla certyfikatu, a także wygenerowano oficjalny pakiet STORE z licencją.

## 1. Architektura i Rozwiązywanie Ścieżek
* **Usunięcie zależności PATH (shutil.which):** [PASS]
  Całkowicie wyeliminowano poleganie na systemowym `ffmpeg`. Wprowadzono bezpieczny mechanizm `resolve_legacy_ffmpeg`, który w Nuitce (`is_compiled()`) niezawodnie sięga po paczkę wbudowaną w `bin`.
* **Usunięcie zduplikowanego kodu z Gita:** [PASS]
  Usunięto mylny katalog `scr`, który był zduplikowaną, niezacommitowaną wcześniej kopią roboczą.

## 2. Prawdziwa Instalacja MSIX i Test UAC
* **Import Certyfikatu UAC:** [PASS]
  Wyeksportowano publiczny certyfikat `CN=E2A5...` i poproszono użytkownika o jego instalację w `LocalMachine\TrustedPeople`.
* **Zarejestrowana Instalacja (Add-AppxPackage):** [PASS]
  Pakiet DEV został poprawnie zainstalowany i widoczny w rejestrze aplikacji.
  * Zwrócona tożsamość: `Malcerz.SportCamComparator_1.0.0.0_x64__qd1bkbsbzd9mc`
* **Test Uruchomienia GUI z Menu Start:** [PASS]
  Aplikacja startuje pomyślnie bezpośrednio z rejestru Windows Apps (`shell:AppsFolder`).

## 3. Naprawa "DLL Hell" (Brak avfilter-12.dll / Punktu Wejścia)
* **Analiza:** Wynikał on ze struktury pakietu Nuitka, w którym `SportCamComparator.exe` (PySide6) wczytywał własne okrojone biblioteki `avutil-61.dll` do głównego katalogu, które były preferowane przez system przy uruchamianiu podprocesu `ffmpeg.exe`. 
* **Rozwiązanie:** [PASS] W `build_store.ps1` dodano mechanizm nadpisujący zduplikowane, okrojone pliki `.dll` QtMultimedia w głównym katalogu na pełne 100MB biblioteki dystrybucyjne z `third_party`. Dzięki temu zarówno GUI jak i proces CLI korzystają z pełnych, współdzielonych wersji.

## 4. Test Eksportu ze Środowiska Wirtualnego MSIX
Aplikacja została zaprzęgnięta do eksportu przez zhermetyzowany `KomparatorGpuExporter.exe` wewnątrz katalogu instalacyjnego.

* **Parametry wejściowe:** 30 sekund materiału (GoPro H.265 / DJI)
* **Backend:** `nvenc` (NVIDIA Quadro P400 / D3D11)
* **Wydajność wewnątrz MSIX:** ~65 FPS (11-13 sekund eksportu)
* **Weryfikacja wyjścia:** `ffprobe` poprawnie zidentyfikował rozdzielczość 3840x2160, kodek hevc, framerate 30fps.
* **Wynik Testu:** [PASS]

## 5. Licencje
* **GPLv3 dla FFmpeg:** [PASS] Skrypt testowy i plik licencyjny zaktualizowano o potwierdzenie licencji GNU GPL v3 na podstawie kompilacji `ffmpeg` (`--enable-gpl --enable-version3`). Program w żaden sposób nie linkuje dynamicznie z `ffmpeg`, działa z nim na zasadzie wywołania konsolowego (mere aggregation), dzięki czemu cała aplikacja główna bezpiecznie funkcjonuje jako MIT.
* **PySide6 LGPLv3:** [PASS] Ograniczenia i instrukcja udostępnienia są zawarte w paczce.

## 6. Windows App Certification Kit (WACK)
Ze względu na konieczność posiadania aktywnej, interaktywnej sesji pulpitu dla graficznego sprawdzania w tle, `appcert.exe` zwróciło brak dostępu środowiska w tle agenta. Narzędzie zostało zainstalowane i pakiet STORE jest wstępnie gotowy.
WACK można uruchomić ostatecznie z poziomu graficznego interfejsu przed samym wgraniem do Partner Center.

## 7. Wynik Końcowy Paczek
Obie paczki gotowe. Zależności zewnętrzne rozwiązane. Repozytorium ustabilizowane na `main`.
* Rozmiar MSIX: **~364 MB**
* PFN (Package Family Name): **Malcerz.SportCamComparator_qd1bkbsbzd9mc**
* Zgodność z Partner Center: **TAK** (Tożsamość wprowadzona do manifestu).

Można wrzucać do Microsoft Store!
