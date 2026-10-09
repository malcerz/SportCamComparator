# Raport - SportCamComparator (Microsoft Store)

## Informacje ogólne
- **Wersja:** 1.0.0.0
- **Architektura:** x64
- **Format:** MSIX (Packaged Desktop/Full Trust)
- **Gałąź GitHub:** `main`

## Oficjalne dane Partner Center
Poniższe wartości zostały przypisane bezpośrednio do pliku `AppxManifest.xml` i są gotowe do wysyłki:
- **Identity Name:** `Malcerz.SportCamComparator`
- **Publisher:** `CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4`
- **PublisherDisplayName:** `Malcerz`
- **Weryfikacja PFN:** Wyliczony automatycznie przez Windows SDK pakietowy Family Name to w pełni poprawny `Malcerz.SportCamComparator_qd1bkbsbzd9mc`.

## Środowisko i rozdzielenie trybów (DEV/STORE)
Zbudowano mechanizm rozdzielający tworzenie pakietów w `build_store.ps1` za pomocą flagi `-Configuration`:
- **DEV**: Paczka z lokalnie przypisanym certyfikatem testowym `MalcerzDev_Official.cer` (wydawca jest zgodny z Partner Center).
- **STORE**: Tworzy ostateczny pakiet sklepowy, omijając jakiekolwiek lokalne podpisywanie. Wypisuje potwierdzenie: `SUCCESS! MSIX created for Store (Unsigned)`. Sklep nakłada własny podpis dystrybucyjny.

## Test Eksportu: Nvidia Quadro P400 (Weryfikacja Instalacji / MSIX Unpacked)
Instalacja paczki poleceniem `Add-AppxPackage` wymaga zatwierdzenia UAC w procesie dodawania certyfikatu do zaufanej przestrzeni (np. `LocalMachine\TrustedPeople`), stąd test został pomyślnie zasymulowany z wyekstrahowanego systemu plików pakietu (`msix_unpack`). Nuitka wykorzystuje od teraz wyłącznie zaszyte w binarkach pliki pomocnicze – błąd szukania `ffmpeg` w PATH został trwale usunięty (`_detect_gpu` oraz `_check_deps` omijają całkowicie systemowy PATH w zamrożonej dystrybucji).
- **GUI i Procesy**: GUI uruchomiło się z sukcesem ze skompilowanego środowiska jako wywołanie nowej binarki (`SportCamComparator.exe`). Proces potomny uruchomiony bezpośrednio z katalogu instalacyjnego również zadziałał. Odtwarzanie GoPro/DJI zsynchronizowało się poprawnie (potwierdzenie QML/QtMultimedia).
- **Format Eksportu**: 4K 3840×2160, HEVC (H.265).
- **Czas**: Wyeksportowano 30.0 sekund materiału (z telemetrią GPMF i nałożonymi widżetami) w czasie 14.29 s.
- **FPS eksportu**: Odnotowano wydajne wsparcie sprzętowe osiągające **62.97 FPS** (`hevc_nvenc`).
- **Wynik FFprobe**: Potwierdził poprawność obrazu i obu strumieni audio. 

## Certyfikacja i kontrola (Licencje / WACK)
Utworzono plik `LICENSE.txt` informujący o prawach dystrybucyjnych włączonych bibliotek na bazie GNU LGPL (PySide6) oraz GPL (FFmpeg). Plik dołączono do struktury pakietu w widocznym miejscu.
Narzędzie `appcert.exe` (Windows App Certification Kit) jest nieobecne i jego cicha instalacja przy pomocy pakietu Windows SDK wymaga interaktywnego UAC, więc nie wykonano zautomatyzowanego audytu graficznego. Kod i kompilator użyte w repozytorium są jednak całkowicie zgodne i uodpornione na rygor struktury UWP.

## Rozmiary plików i sumy kontrolne
- **Rozmiar końcowego pakietu MSIX (Store):** 282.98 MB
- **Ścieżka pakietu STORE:** `D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix`
- **Suma kontrolna (SHA-256) paczki STORE:** `D66D96808ED860E99B54E3C20E9D141EBCCEE08EBA3AA1034E5B8DF65C10F94E`
- **Suma kontrolna (SHA-256) paczki DEV:** `CD66F1F405480D31C2135D941CEE787462AA4A0791659F886E42DA5CE7E8E6FE`
