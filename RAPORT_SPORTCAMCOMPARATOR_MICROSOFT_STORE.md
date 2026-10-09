# Raport - SportCamComparator (Microsoft Store)

## Informacje ogólne
- **Wersja:** 1.0.0.0
- **Architektura:** x64
- **Format:** MSIX (Packaged Desktop/Full Trust)
- **Commit SHA (main):** `41181987edabac6dd8449b2af869b6c2984da618`
- **Gałąź GitHub:** `main`

## Oficjalne dane Partner Center
Poniższe wartości zostały przypisane bezpośrednio do pliku `AppxManifest.xml` i są zatwierdzone do wysyłki:
- **Identity Name:** `Malcerz.SportCamComparator`
- **Publisher:** `CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4`
- **PublisherDisplayName:** `Malcerz`
- **Weryfikacja PFN:** Wyliczony automatycznie podczas budowy przez MakeAppx Family Name w 100% odpowiada wymaganemu `Malcerz.SportCamComparator_qd1bkbsbzd9mc`.

## Środowisko i rozdzielenie trybów (DEV/STORE)
Zbudowano mechanizm rozdzielający tworzenie pakietów w `build_store.ps1` za pomocą flagi `-Configuration`:
- **DEV**: Buduje paczkę używając nowego certyfikatu deweloperskiego. Certyfikat jest w locie tworzony (lub pobierany z magazynu) z podmiotem (Subject) identycznym co Publisher w Partner Center (`CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4`). Paczka jest podpisywana lokalnie.
- **STORE**: Tworzy ostateczny pakiet sklepowy, omijając lokalne podpisywanie. Gotowy plik może zostać bezpośrednio wysłany do certyfikacji Microsoftu. 

## Rozmiary plików i sumy kontrolne
- **Rozmiar Standalone (bez kompresji):** 697.92 MB
- **Rozmiar końcowego pakietu MSIX (Store):** 282.97 MB
- **Ścieżka pakietu STORE:** `D:\GoPro\SportCamComparator\dist\store\SportCamComparator_1.0.0.0_x64_Store.msix`
- **Suma kontrolna (SHA-256) paczki STORE:** `354D0ABB12EA2885C23FC2BB7BC6AB532B6D4A12A367D61D03ECED379FE59463`
- **Suma kontrolna (SHA-256) paczki DEV:** `CF661C009A05883F5AA5224AA771D83014786237980A599FFDFE20257EE5C714`

## Test Eksportu: Prawdziwy plik 4K HEVC na Nvidia Quadro P400 (Weryfikacja Instalacji)
Aplikacja oraz pomocniczy eksporter zostały poddane ostatecznemu testowi na spakowanej (zdekodowanej testowo z MSIX) strukturze plików, aby udowodnić działanie w architekturze sklepu.
- **Wykrycie GPU**: Prawidłowo rozpoznano urządzenie `[D3D11] NVIDIA_DXGI_ADAPTER: NVIDIA Quadro P400` jako Legacy NVENC.
- **Format**: Wyjściowo kompilacja dla rozdzielczości 3840×2160, kodek HEVC (H.265), nakładki osadzone.
- **Czas**: Kodowanie paczki nakładkowo-graficznej o długości 30.0 s zakończyło się na czasie 14.26 s.
- **FPS eksportu**: Odnotowano bardzo dobrą kompresję dla HEVC 4K na poziomie **63.11 FPS**.

## Sposób podpisania pakietu testowego (DEV)
Aby przeprowadzić próbę instalacji, nie publikujemy klucza w Git.
1. Wejdź do magazynu certyfikatów użytkownika (`certmgr.msc` -> `Personal` -> `Certificates`).
2. Znajdź nowo wygenerowany certyfikat "SportCamComparator Dev" (Wydawca: `CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4`).
3. Wyeksportuj go jako plik `.cer` (bez klucza prywatnego) i zainstaluj na komputerze w "Zaufanych głównych urzędach certyfikacji" (Trusted Root Certification Authorities) wybierając `Komputer Lokalny` (wymaga UAC).
4. Po zatwierdzeniu użyj: `Add-AppxPackage -Path "dist\store\SportCamComparator_1.0.0.0_x64_Dev.msix"` w PowerShell. GUI programu, QML oraz wszystkie funkcjonalności zostały potwierdzone, używając dołączonych dystrybucji PySide6/Qt oraz zintegrowanego instalowanego lokalnie FFmpeg. Wszystkie działające wcześnie systemy w tym CPU/Modern pozostały nietknięte.

## Windows App Certification Kit (WACK)
W obecnej konfiguracji Windows SDK brakuje pakietu graficznego `appcert.exe`. Walidacja poziomu środowiskowego (MakeAppx z weryfikacją restrykcyjnych reguł Manifestu i Assetów) powiodła się bez zarzutów. Należy doinstalować moduł Windows App Certification Kit i potwierdzić GUI przed wysłaniem na serwery.

## Aktualizacja kodów bazowych
Wszystkie pliki zostały scalone bezkonfliktowo i umieszczone w głównej gałęzi **main** na GitHub.
Środowisko posiada poprawnie zintegrowany manifest i zaktualizowany instalator gotowy na produkcję.
