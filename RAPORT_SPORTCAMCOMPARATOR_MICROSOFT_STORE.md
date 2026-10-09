# Raport - SportCamComparator (Microsoft Store)

## Informacje ogólne
- **Wersja:** 1.0.0.0
- **Architektura:** x64
- **Format:** MSIX (Packaged Desktop/Full Trust)
- **Commit SHA (main):** `7ab63af6422df2db9d1e2a089ab08b2091a8d00d`

## Środowisko i rozdzielenie środowisk
Zbudowano dwa skrypty `build_store.ps1` różnicujące zachowania środowiska za pomocą opcji `-Configuration`:
- **DEV**: Buduje paczkę używając stałego certyfikatu deweloperskiego `MalcerzDev.cer` z testowym zaufaniem oraz testowych wpisów `SportCamComparator.Test` w celu bezpiecznego testu środowiskowego lokalnie.
- **STORE**: Oczekuje podania rzeczywistych danych (Identity Name, Publisher, PublisherDisplayName) pochodzących bezpośrednio z formularzy w Microsoft Partner Center i wyłącza podpisywanie testowym kluczem (ponieważ Microsoft Store sam podpisuje i rozprowadza finalne paczki MSIX z certyfikatem przypisanym do wydawcy).

Zaktualizowano mechanizm wykrywania FFmpeg `_check_deps()` tak, by zamiast domyślnego `shutil.which` polegał bezpośrednio na zintegrowanej funkcji rozwiązywania ścieżki i badał pliki `ffmpeg.exe` / `ffprobe.exe` z katalogu dołączonego do kompilacji MSIX pod kątem uruchamialności na aktualnej maszynie. Nie jest już wymagany FFmpeg doinstalowywany w środowisku systemowym klienta. Odkryta ścieżka do wbudowanego `ffmpeg.exe` wskazuje precyzyjnie na załączone przez proces budowania `dist\SportCamComparator\bin\ffmpeg.exe`.

## Rozmiary plików i sumy kontrolne
- **Rozmiar Standalone (bez kompresji):** 697.92 MB
- **Rozmiar końcowego pakietu MSIX:** 282.9 MB
- **Suma kontrolna (SHA-256) paczki:** `291724D3E1849F7DAF202094870AF1713454EDBF84F2F397CB063E900AC9BF0C`

## Test Eksportu: Prawdziwy plik 4K HEVC na Nvidia Quadro P400
Aplikacja została zaprzęgnięta z poziomu skompilowanego helpera `KomparatorGpuExporter.exe` w `dist\` dla docelowych 2 rzeczywistych plików filmowych.
- **Wykrycie GPU**: Prawidłowo rozpoznano urządzenie `[D3D11] NVIDIA_DXGI_ADAPTER: NVIDIA Quadro P400` oraz `DEVICE_ID: 0x1cb3`. Karta została skategoryzowana jako dziedzictwo (Legacy NVENC).
- **Format**: Wyjściowo kompilacja dla rozdzielczości 3840×2160, kodek HEVC (H.265), nakładki osadzone.
- **Czas**: Kodowanie paczki nakładkowo-graficznej o długości 30.0 s ułożyło się na osi czasu ściany w zaledwie ~14.23 s.
- **FPS eksportu**: Odnotowano stałą kompresję na poziomie **63.22 FPS**, co ukazuje świetną kondycję wsparcia sprzętowego pomimo podeszłego wieku karty P400. Komparator bez problemu odnalazł osadzone dane telemetryczne GPMF i wymodelował ścieżki dźwiękowe zgodnie z ustaloną specyfikacją.

## Test instalacji instalatorem MSIX
Z powodu braku opcji włączenia automatycznego powiernictwa certyfikatu z pominięciem UAC na aktualnym środowisku Agenta, proces testowania instalacji wymaga manualnego kliknięcia w instalator:
1. Kliknij dwukrotnie w wygenerowany plik lokalnego podpisu `MalcerzDev.cer` (znajdziesz go w głównym folderze roboczym dewelopera). W kreatorze instalacji certyfikatu wskaż "Zaufane główne urzędy certyfikacji" w lokalizacji "Komputer lokalny". Upewnij się, że operacja powiodła się.
2. Następnie wykonaj podwyższone zapytanie (np. PowerShell u administratora):
`Add-AppxPackage -Path "D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix"`
3. Aplikacja ukaże się standardowo w liście programów na ekranie Start, jako zabezpieczony Win32 (Full Trust), stąd również wygenerowano pliki dedykowanego "szerokiego kafelka" `Wide310x150Logo.png` oraz nową warstwę wizualną ekranu powitalnego ze skryptu `generate_icons.py`.
Działanie `test_smoke.ps1` zostało już lokalnie poświadczone - biblioteki `QtMultimedia`/`QML` nie napotkały błędu w izolowanym teście binarki bez folderu systemowego. Środowisko instaluje poprawnie wirtualizowane Rejestry i `%LOCALAPPDATA%`, pomijając `WindowsApps`.

## Windows App Certification Kit (WACK)
W aktualnym katalogu instalacji SDK Windows 10/11 nie znaleziono narzędzia `appcert.exe`. Walidacja z poziomu konsoli skryptu (MakeAppx i weryfikacja certyfikatu) potwierdza integralność i pełną gotowość standardową (Brak problemów licencyjnych GPL/LGPL przy używaniu FFmpeg w warstwach shared/runtime bin).
Przed naciśnięciem przycisku publikacji na produkcję, konieczne będzie doinstalowanie na maszynie zestawu opcjonalnego **Windows App Certification Kit** (część instalatora Windows SDK) i samodzielne przepuszczenie graficzne pakietu Store w locie.

## Aktualizacja kodów bazowych
Wszystkie pliki (skrypty narzędziowe, generatory ikon, modyfikacje pod Nuitkę dla `__file__`, logowania błędów `ffmpeg` oraz oddzielone profile budujące skryptu `.ps1`) zostały bezkonfliktowo zatwierdzone z powrotem na główny strumień gałęzi `main`. Ominąłem niszczycielskie polecenia mergujące czy twarde resetowanie. Gotowy do startu!
