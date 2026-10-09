# Raport: naprawa AMD D3D11 — kolory i nakładki

Data: 2026-10-09  
Repozytorium źródłowe: SportCamComparator
GPU: AMD Radeon (TM) Graphics, Vendor ID 0x1002, Device ID 0x15e7, LUID 00000000:0000b3e4, sterownik 31.0.21925.1001  
Materiały testowe:
- DJI_20261005062901_0004_D.MP4
- GX010344.MP4

## Wynik

Na tym AMD udało się ustabilizować natywny eksport D3D11VA → AMF. Finalny eksport 30 s z dwoma nakładkami, obrotem 180° obu wejść i układem lewo/prawo zakończył się sukcesem. Obraz ma poprawne kolory, czytelne nakładki i czarne pasy. Liczniki pełnoklatkowych transferów GPU→CPU i CPU→GPU oraz licznik klatek programowych pozostały zerowe.

## Ustalenia

FFprobe wykazał dwa źródła HEVC Main 10, 3840×2160, yuv420p10le:

| Źródło | Range | Matrix | Primaries | Transfer | Display Matrix |
|---|---|---|---|---|---|
| DJI | limited (tv) | BT.709 | BT.709 | BT.709 | −180° |
| GoPro | full (pc) | BT.2020 NCL | BT.2020 | HLG (arib-std-b67) | −180° |

Obie powierzchnie D3D11VA były P010 (DXGI_FORMAT_P010, wartość 104), tekstury 3840×2176, array size 20, bind flags 0x200. AVHWFramesContext.sw_format raportował p010le. Nie były to klatki NV12 8-bit.

Sterownik AMD zgłaszał obsługę wejścia i wyjścia dla NV12 (DXGI 103), P010 (104) i BGRA8 (87). MaxInputStreams=52; FeatureCaps=0x8e6; capability rotacji była dostępna. Sama liczba wejść ani obrót 180° nie wyjaśniają błędu.

Przed poprawką Video Processor przyjmował oba filmy P010, ale wywołanie z dołączoną nakładką BGRA kończyło się na pierwszej klatce VideoProcessorBlt, E_FAIL (0x80004005). Wariant z czterema bezpośrednimi strumieniami także zawodził. Format BGRA i P010 każdy osobno przechodził test capability. Wynik wskazuje na odrzucaną przez sterownik kombinację strumieni w jednym blitcie, mimo że formaty i limit strumieni są indywidualnie obsługiwane. Rotacja była wspierana.

Różowy/fioletowy obraz wynikał z braku jawnego, właściwego dla każdego wejścia stanu przestrzeni barw w Video Processorze. Miało to znaczenie zwłaszcza dla pełnozakresowego HLG/BT.2020 GoPro. Samo ustawienie przestrzeni wyjściowej nie wystarczało. Konfiguracja strumienia z metadanych wraz z przejściem przez BGRA usunęły widoczny zafarb. Nie dodano ręcznego filtra tone mapping.

## Zastosowana kompozycja

Zmiana jest ograniczona do AMD (VendorId == 0x1002):

1. Video Processor dostaje dwa strumienie filmów P010 i jawne ColorSpace1/range na podstawie metadanych każdego wejścia; wykonuje obrót i układ obrazu.
2. Wyjściem etapu jest powierzchnia BGRA. Tekstury telemetrii nie są dodawane jako wejścia Video Processora.
3. Shader D3D11 nakłada tekstury BGRA Direct2D z prawidłowym mieszaniem premultiplikowanego alfa (src + dst × (1 − alpha)).
4. Drugi przebieg Video Processora konwertuje BGRA do NV12 dla AMF. Metadane wyjściowe AMF są oznaczone jako BT.709 limited.

NVIDIA, Intel i CPU nie przechodzą przez nowy shader AMD. Nie dodano pełnoklatkowego hwdownload/hwupload. Nie wprowadzono fallbacku, bo natywna ścieżka D3D11 zadziałała.

## Próby Video Processor A–F

Każda próba korzystała z tej samej pary plików, wyjścia 3840×2160, była uruchomiona kolejno i testowała rzeczywisty eksport oraz VideoProcessorBlt. Po poprawce wszystkie blitty zwróciły sukces (S_OK, HRESULT 0x0). Video Processor widział dwa wejścia w każdym wariancie; nakładki AMD były mieszane shaderem.

| Próba | Obrót | Nakładki | Padding | Wynik | FPS |
|---|---:|---:|---:|---|---:|
| A | 0° | 0 | nie | PASS, 30 klatek | 26.33 |
| B | 180° | 0 | nie | PASS, 30 klatek | 27.93 |
| C | 0° | 2 | nie | PASS, 30 klatek | 28.20 |
| D | 180° | 2 | nie | PASS, 30 klatek | 28.47 |
| E | 180° | 0 | tak | PASS, 30 klatek | 27.12 |
| F | 180° | 2 | tak | PASS, 30 klatek | 27.98 |

Dla testów E/F oba wejścia były już 3840×2160, a konfiguracja kompozytu także wynosiła 3840×2160. Flaga paddingu została przećwiczona, ale nie mogła dodać dodatkowych pasów do większego płótna. Czarne pasy i proporcje sprawdzono wizualnie w gotowym kompozycie. Osobny test góra/dół z dwiema nakładkami również przeszedł.

## Eksporty akceptacyjne i kontrola obrazu

- Bez nakładek: 900 klatek / 30.03 s, 26.08 FPS.
- Z dwiema nakładkami: 900 klatek / 30.03 s, 25.41 FPS, 35.42 s czasu ściennego.
- Oba eksporty: HEVC Main, 3840×2160, yuv420p, limited BT.709; AAC LC stereo 48 kHz. FFprobe potwierdził długość wideo 30.03 s i audio 30.016 s.
- Finalny obraz z nakładkami sprawdzono wzrokowo: prawidłowa orientacja obu obrazów, naturalny wygląd kolorów, widoczne etykiety/telemetria i czarne pasy. Sprawdzono również widok góra/dół.
- Anulowanie: eksport przerwano po 46 klatkach; helper zwrócił status cancelled, zapisał poprawnie sfinalizowany częściowy MP4, z zerowymi licznikami transferów. Następny eksport 1 s zakończył się success (30 klatek).
- Zero-copy: w eksportach 30 s i testach A–F full_frame_hwdownload_count=0, full_frame_hwupload_count=0, software_frame_count=0.

Diagnostyczny profil 3 s dla finalnego shadera: średni COMPOSITOR_MS=1.75 ms, COMPOSITOR_GPU_MS=36.86 ms, nierozstrzygnięte zapytania GPU: 0. Proces zużywał średnio 32.8% jednego logicznego rdzenia (około 2.1% sumy 16 logicznych procesorów). Odczyt wykorzystania GPU z Windows miał tylko cztery próbki i sumował kilka silników, więc nie jest miarodajną wartością procentową całego GPU. Pomiar 25.41 FPS z eksportu 30 s jest stabilniejszym wynikiem całej ścieżki niż osobny odczyt silników.

Dostępny punkt odniesienia przed poprawką to krótki eksport bez nakładek około 24.9 FPS. Nie jest to porównanie A/B o tej samej długości, więc nie wyciągam z niego wniosku o przyspieszeniu. Dla wariantu z nakładkami przed poprawką eksport kończył się na klatce 0, więc nie ma bazowego FPS.

## Opcje i regresje

W zrzucie Opcji próba AMF dla płótna lewo/prawo 7680×2160 zwracała wieloliniowy błąd FFmpeg. Wyłączenie Podwójnego 4K wynikało z nieudanego testu inicjalizacji kodera dla docelowego wymiaru. Poprawiłem UI: Opcje pokazują teraz krótki powód z koderem i rozmiarem, a pełny diagnostyczny tekst zostaje w logu.

Po zmianach:
- python -m compileall -q src tests — PASS.
- python -m pytest -q — 221 passed, 2 skipped. Testy NVENC pomijają się tylko, gdy system nie ma karty NVIDIA; obecny komputer testowy ma AMD.
- Natywny KomparatorGpuExporter.exe przebudowany konfiguracją Release; test capability AMF/D3D11 zakończył się powodzeniem.

Nie wykonano osobnego pomiaru próbek Y/Cb/Cr ani diagnostycznego odczytu powierzchni przed AMF. Ocena koloru opiera się na metadanych źródeł/D3D11VA, porównaniu obrazu źródłowego z finalnymi klatkami oraz FFprobe gotowego MP4. Nie uruchamiałem też eksportu do płótna 7680×2160 po naprawie — zrzut pokazuje, że bieżący test legacy AMF tego wymiaru nie potwierdza, więc opcja pozostaje bezpiecznie wyłączona.
