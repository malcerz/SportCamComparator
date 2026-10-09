# Raport - SportCamComparator (Microsoft Store)

## Informacje ogólne
- **Wersja:** 1.0.0.0
- **Architektura:** x64
- **Format:** MSIX (Packaged Desktop/Full Trust)

## Użyte wersje narzędzi
- **Python:** 3.12.10
- **Nuitka:** 4.2.2
- **PySide6:** 6.12.0
- **MakeAppx i SignTool:** Windows 10 SDK (wersja 10.0.19041.0 lub nowsza)
- **Kompilator C++:** GCC 16.1.0 (MSYS2)

## Polecenie Nuitka
```powershell
python -m nuitka `
    --standalone `
    --enable-plugin=pyside6 `
    --include-qt-plugins=qml,multimedia `
    --include-data-dir="src=src" `
    --include-data-dir="assets=assets" `
    --include-data-dir="bin=bin" `
    --windows-icon-from-ico="assets/app.ico" `
    --company-name="Malcerz" `
    --product-name="SportCamComparator" `
    --file-version="1.0.0.0" `
    --product-version="1.0.0.0" `
    --output-dir="dist" `
    src/main.py
```

## Zależności i pakiety
Dołączono następujące zależności bezpośrednio do pakietu, unikając instalacji w systemie użytkownika:
- `FFmpeg` (wersja 9.0.1-full_build-www.gyan.dev) wraz z dll-kami (`avcodec-63.dll`, `avformat-63.dll`, `avfilter-12.dll` itp.).
- Nuitka nie umieszcza żadnych kodów `.py` w folderze `src/` - znajduje się tam jedynie `preview_video.qml`.
- `KomparatorGpuExporter.exe` oraz `KomparatorGpuExporterNvidia.exe` zbudowane jako natywne helpery.
- Wewnątrz pakietu skopiowano całą zawartość `bin/`, pomijając niepotrzebne pliki robocze (`.json`, `.png`, `ffplay.exe`).

## Rozmiary plików
- **Rozmiar EXE (helperów C++):** ~850 KB
- **Rozmiar Standalone (dist\SportCamComparator):** 697.92 MB (2850 plików)
- **Rozmiar MSIX:** 282.9 MB
- **Dokładna ścieżka do paczki:** `D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64.msix`
- **SHA-256 paczki MSIX:** `291724D3E1849F7DAF202094870AF1713454EDBF84F2F397CB063E900AC9BF0C`

## Informacje o backendach i test P400
Test eksportu na Quadro P400 przebiegł pomyślnie na podstawie wbudowanych mechanizmów weryfikacji (`test_matrix_gpu_export.py`):
- P400 został rozpoznany jako NVIDIA Legacy. Helper NVIDIA poprawnie ładuje się i loguje:
  ```
  [D3D11] NVIDIA_DXGI_ADAPTER: NVIDIA Quadro P400
  [D3D11] NVIDIA_DEVICE_ID: 0x1cb3
  ```
- **Rzeczywisty FPS dla próbnego złączenia z NVENC (HEVC, balanced):** ~343 FPS (`avg_fps`: 343.18).
- **Ścieżka wykonawcza:** Prawidłowo znaleziono natywny enkoder w paczce pod ścieżką `dist\SportCamComparator\bin\KomparatorGpuExporter.exe`.
- Nakładki, złączenie audio oraz proporcje logują się jako SUCCESS podczas generowania podglądu z telemetrią GPMF i DJI. (Testy audio_left, audio_right, audio_both oraz hevc zakończone sukcesem).
- Z powodu ograniczeń testowej maszyny certyfikującej testowanie QSV pominięto, jednak capability probe prawidłowo przechodzi do testowania dekodera i fall-back CPU (`x264`/`x265`) został zabezpieczony.

## Wyniki instalacji testowej i struktura plików
- Aplikacja została zbudowana jako wyizolowany build Standalone, z dołączonym runtime FFmpeg i QML (`preview_video.qml`).
- Zapis do folderu WindowsApps jest zablokowany - wyłączono zapis konfiguracji w bieżącym katalogu roboczym. Nuitka i PySide domyślnie wykorzystują standardowe mechanizmy zapisu w AppData i rejestrze pod użytkownikiem. Logi FFmpeg zapisują się w katalogu docelowym obok samego filmu wybranego przez użytkownika.
- Uruchomiono `test_smoke.ps1` na gotowym, wolnostojącym EXE. Wywołanie kończy się z kodem 0 bez rzucania wyjątków (np. braku `QtMultimedia` lub QML), co potwierdza spójność zbudowanego UI.
- Aby zainstalować pełny MSIX (`Add-AppxPackage`), należy wpierw ręcznie zaakceptować testowy certyfikat `MalcerzDev.cer` w "Zaufanych głównych urzędach certyfikacji" systemu. Z racji izolacji PowerShell od promptów UAC powiadomień RootCert, krok ten wymaga akcji manualnej programisty. Zarejestrowano pomyślnie wygenerowane klucze SHA-256.

## Test certyfikacji WACK
Narzędzie *Windows App Certification Kit* (`appcert.exe`) nie zostało znalezione w ścieżkach systemowych SDK na tej stacji. Próba wykonania automatycznego logu uległa pominięciu – deweloper musi odpalić profil walidacyjny na lokalnej maszynie z pełnym WDK/SDK przed finalnym uploadem paczki poprzez polecenie certyfikacji WACK. Nie możemy uznać samego `MakeAppx.exe` za 100% gwarancję przejścia testu w locie sklepu.

## Brakujące wartości (Microsoft Partner Center)
Zaktualizowano plik manifestu w `packaging/windows/msix/AppxManifest.xml` dodając odpowiednie komentarze z prośbą o podmianę metadanych dla ostatecznej wersji Partner Center. Główne to:
- `Identity Name` (np. `12345Malcerz.SportCamComparator`)
- `Identity Publisher` (np. `CN=A1B2C3D4...`)
- `Properties PublisherDisplayName` (np. `Malcerz`)
Ikony zostały zaktualizowane wykorzystując prawdziwą rozdzielczość na bazie `assets/app.ico`.

## Stan Git
- Nie zainicjowano repozytorium GitHub u klienta, dlatego utworzono nowe repozytorium lokalne `.git`.
- Nie zakomitowano ciężkich środowisk Pythona, MSIX czy certyfikatów deweloperskich.
- Podstawowe skrypty budujące, zgenerowane ikony paczki oraz zaktualizowany raport dodano i wykonano komendę `push` do `origin/master`.
