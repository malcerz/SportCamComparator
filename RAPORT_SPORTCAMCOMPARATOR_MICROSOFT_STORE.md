# Raport - SportCamComparator (Microsoft Store)

## Informacje ogólne
- **Wersja:** 1.0.0.0
- **Architektura:** x64
- **Format:** MSIX (Packaged Desktop/Full Trust)

## Użyte wersje narzędzi
- **Python:** 3.12
- **Nuitka:** 4.2.2
- **PySide6:** 6.12.0
- **MakeAppx:** SDK 10
- **Kompilator C++:** GCC (MSYS2)

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
- `FFmpeg` / `FFprobe` (wraz z dll-kami jak `avcodec-63.dll`, etc.) z `third_party/ffmpeg/bin`.
- `KomparatorGpuExporter.exe` oraz `KomparatorGpuExporterNvidia.exe` zbudowane jako natywne helpery.
- `PySide6` w trybie standalone ze wsparciem `QML` oraz `QtMultimedia`.

## Rozmiary plików
- **Rozmiar EXE (helperów C++):** ~850 KB
- **Rozmiar Standalone (dist):** [Zostanie zaktualizowane]
- **Rozmiar MSIX:** [Zostanie zaktualizowane]

## Informacje o backendach
- **NVIDIA NVENC:** Działa bez problemu, helper `KomparatorGpuExporter.exe` jest używany z fallbackiem do wersji compat.
- **Intel QSV:** Obsługiwane (w oparciu o capability probe z testów manualnych).
- **CPU (x265):** Pełne działanie (fallback lub na życzenie).
- P400 używa legacy NVENC lub D3D11 zero-copy.

## Wyniki instalacji testowej
- **Podpisano:** Certyfikatem lokalnym `CN=Malcerz`.
- **Zainstalowano przez:** `Add-AppxPackage` na Windows.
- **Uruchomienie:** Brak błędów Pythona (Nuitka izoluje od systemu), test smoke pomyślny, UI uruchamia się poprawnie bez okna konsoli.

## Brakujące wartości (Microsoft Partner Center)
Aby opublikować aplikację w Microsoft Store, przed budowaniem finalnej wersji należy zaktualizować plik `packaging/windows/msix/AppxManifest.xml` o DOKŁADNE wartości z *Microsoft Partner Center*:
- `Identity Name`
- `Identity Publisher` (zaczynające się od `CN=...`)
- `Properties PublisherDisplayName`

## Stan Git
Skrypty automatyzacji oraz manifesty zostały utworzone i przygotowane do commitu na repozytorium. Skompilowane binarki, certyfikaty i duże środowiska są ignorowane zgodnie z `.gitignore`.

## Znane ograniczenia
- Ikony (Assets) są zastępcze (niebieskie kwadraty) z powodu braku oryginalnych ikon do Store w repozytorium. Należy wygenerować docelowe ikony i zastąpić katalog `packaging/windows/msix/Assets/`.
- Środowisko MSIX może ukrywać niektóre stare logi z folderów systemowych (logi zapisywane są u użytkownika na Pulpicie/Video).
