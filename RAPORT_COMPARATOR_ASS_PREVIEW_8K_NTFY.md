# RAPORT_COMPARATOR_ASS_PREVIEW_8K_NTFY

Data pomiarów: 8 października 2026 r.  
Sprzęt: NVIDIA GeForce RTX 5070 Ti, compute capability 12.0.  
Materiały: `K:\GoPro\2026-10-06\GX010345.MP4` (GoPro, 3840×2160, 55 672 próbki GPMF) i `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4` (DJI, 3840×2160, 56 453 próbki natywnej telemetrii). Oba pliki zawierają obrót Display Matrix −180°, normalizowany przed ASS i złożeniem.  
Kodek w pomiarach: HEVC NVENC p4, 10 Mbit/s, wyjściowe 29,97 fps. Wyniki mierzone sekwencyjnie, bez konkurujących przebiegów FFmpeg.

## ASS: koszt rzeczywistych nakładek

A/B/C/D używają tych samych rzeczywistych kamer, CUDA decode, transferu do CPU dla filtrów ASS, orientacji, stacku, wyjścia 3840×2160, p4, bitrate i FPS. W A oba ASS są wyłączone; B ma ASS pierwszej kamery, C drugiej, D obie. Każdy wariant miał osobny przebieg rozgrzewkowy 300 klatek i dwa przebiegi pomiarowe po 3000 klatek. Mierzono czas procesu FFmpeg od startu do zamknięcia.

| Wariant | Średnie FPS (2 przebiegi) | ms/klatkę | Koszt względem A |
|---|---:|---:|---:|
| A: bez ASS | 137.52 | 7.272 | — |
| B: ASS kamery 1 | 136.38 | 7.333 | 0.83% |
| C: ASS kamery 2 | 136.32 | 7.336 | 0.88% |
| D: ASS obu kamer | 135.10 | 7.402 | **1.76%** |

Średnia z próbek monitoringu obu pomiarów (CPU pokazany jako procent jednego logicznego rdzenia; ok. 400% to cztery rdzenie procesu):

| Wariant | FFmpeg speed | CPU procesu | GPU | NVENC | NVDEC |
|---|---:|---:|---:|---:|---:|
| A | 4.63× | 434% | 18.9% | 49.0% | 62.0% |
| B | 4.61× | 446% | 18.6% | 47.8% | 61.4% |
| C | 4.61× | 443% | 18.1% | 48.9% | 62.0% |
| D | 4.58× | 442% | 17.3% | 46.1% | 59.8% |

Oba osobne napisy kosztują łącznie około 2.42 fps (0.131 ms na klatkę) w krótkim pomiarze. Pełne MP4 z audio dały 140.82 fps bez ASS i 140.27 fps z oboma ASS (0.39% różnicy). Pełne materiały mają około 31,4 minuty; eksporty trwały odpowiednio 400.9s i 402.5s.

ASS pozostaje przypisany do właściwej kamery i jest nakładany przed stackiem. Nie przeniesiono go po kompozycji: napisy mają różne dane/pozycje kamery, a ich scalanie zmieniłoby relację współrzędnych obrazu i synchronizacji. Nie wykazano identyczności obrazu, która uzasadniałaby zmianę. ASS nadal renderuje się na żywo w eksporcie; nie powstają pośrednie bitmapy ani filmy.

## Dopełnianie 16:9 i rzeczywiste rozmiary

Checkbox **Dopełniaj czarnymi pasami do formatu 16:9** jest domyślnie zaznaczony. Wymiary kompozytu są widoczne w opcjach i zależą od checkboxa. Niepełny obraz jest centrowany, bez skalowania i przycinania; końcowy `pad` działa po złożeniu kamer, więc ASS nie jest malowany na pasach.

| Tryb | Bez dopełnienia | Z dopełnieniem |
|---|---:|---:|
| Standard 2160p, góra/dół | 1920×2160 | 3840×2160 |
| Standard 2160p, lewo/prawo | 3840×1080 | 3840×2160 |
| Podwójne 4K, góra/dół | 3840×4320 | 7680×4320 |
| Podwójne 4K, lewo/prawo | 7680×2160 | 7680×4320 |

Weryfikacja rzeczywistymi 30-klatkowymi MP4 przez FFprobe: HEVC 3840×4320, 7680×4320, 7680×2160 i 7680×4320 odpowiednio dla czterech wariantów Dual 4K. Pomniejszone klatki PNG sprawdzono próbkami pikseli na krawędziach: pasy wyjściowe są RGB (0,0,0). Nie wykonano skalowania kompozytu.

### RTX 5070 Ti, Dual 4K, pomiar wydajności

Każdy wariant miał 300 klatek warm-up oraz dwa mierzone przebiegi po 3000 klatek. Wykorzystano źródła 4K, orientację, dwa rzeczywiste ASS, HEVC p4, 10 Mbit/s i `-split_encode_mode forced`.

| Kompozyt | Średnie FPS | FFmpeg speed (powtórzenia) | Peak RSS | Peak VRAM |
|---|---:|---:|---:|---:|---:|
| Góra/dół 3840×4320 bez pasów | 54.27 | 1.82× / 1.83× | 2606 MiB | 3910 MiB |
| Góra/dół 7680×4320 z pasami | 38.54 | 1.32× / 1.27× | 3694 MiB | 4557 MiB |
| Lewo/prawo 7680×2160 bez pasów | 52.52 | 1.76× / 1.77× | 2609 MiB | 3911 MiB |
| Lewo/prawo 7680×4320 z pasami | 38.71 | 1.31× / 1.29× | 3694 MiB | 4557 MiB |

Przejście z surowego kompozytu do pełnego 8K obniżyło FPS o 29.0% dla góra/dół i 26.3% dla lewo/prawo. Pełny 8K koduje dwa razy więcej pikseli niż odpowiedni surowy kompozyt, więc ten spadek jest oczekiwanym kosztem większej klatki. Poprzednie ręczne około 90 fps dla 3840×4320 nie zostało powtórzone przez ten przebieg pełnym grafem produkcyjnym: wynik 54,27 fps obejmuje dwa źródła 4K, korektę obrotu, oba ASS, 29,97 fps i pomiar 3000 klatek. Różnica warunków jest istotna; nie przypisujemy jej pojedynczemu filtrowi.

Capability probe sprawdza dokładny rozmiar wynikowy i wymusza split encode. Pełny 8K nie jest po cichu zmniejszany; przy braku obsługi opcja nie jest dostępna/zgłasza powód.

## Podgląd eksportu

Podgląd jest drugą gałęzią tego samego końcowego kompozytu: próbkuje 2 fps, skaluje do 320×180 i dostarcza JPEG przez loopback UDP z FIFO ograniczonym do dwóch elementów i odrzucaniem starych klatek. GUI wyświetla najnowszą próbkę z timerem 0,5 s. Nie powstaje drugi decode ani plik pośredni; główny strumień HEVC nie jest ponownie kodowany.

Pełne eksporty z oboma ASS i audio, po 56 453 klatki:

| Tryb | Średnie FPS | Czas | Peak RSS | Peak VRAM |
|---|---:|---:|---:|---:|
| Podgląd wyłączony | 139.92 | 403.5s | 2001 MiB | 3735 MiB |
| Podgląd włączony | 139.33 | 405.2s | 2076 MiB | 3640 MiB |

Koszt zmierzony dla preview wyniósł **0.42%** (spadek 0.59 fps), a odbiornik odebrał 784 próbki podczas pełnego eksportu. FFprobe potwierdził 3840×2160 HEVC + AAC, czas 1883,650 s i kompletną liczbę klatek w obu plikach. Odtwarzacz przywraca się po sukcesie, błędzie i anulowaniu. Integracyjne testy obejmują anulowanie/odtworzenie stanu; ręczny test kliknięcia anulowania w otwartym GUI nie był częścią tej sesji.

## ntfy

Ustawienia ntfy były dostępne w opcjach i zapisywane przez QSettings: domyślny serwer `https://ntfy.sh`, test połączenia oraz konfigurowalny temat (wartość użytkownika pominięta w tym raporcie). Wysyłka HTTP POST jest asynchroniczna, timeout 5 s, krótki bezpieczny tekst bez prywatnych ścieżek. Nagłówek tytułu z polskimi znakami jest kodowany zgodnie z RFC 2047. Zakończenie eksportu wysyła maksymalnie jedno powiadomienie; sukces następuje dopiero po kodzie FFmpeg 0, istnieniu pliku i poprawnej walidacji FFprobe.

Testowe powiadomienie wysłano na skonfigurowany temat ntfy; serwer odpowiedział HTTP 200. Treść testu nie zawierała danych osobowych ani ścieżek. Testy automatyczne obejmują sukces, błąd, anulowanie, jednokrotność, HTTP error, timeout, walidację adresu/tematu i pracę w wątku daemon.

## Zmiany w kodzie

Główne pliki:

- `src/options_dialog.py`, `src/i18n.py` — checkbox dopełniania, wymiary wyjściowe, opcja podglądu i konfiguracja/test ntfy.
- `src/nvidia_modern.py`, `src/export_prepare.py` — dokładne wymiary/proby Dual 4K, końcowe centrowane dopełnianie, osobna gałąź preview oraz konfiguracja D3D11.
- `src/export_live_preview.py`, `src/main.py` — odbiornik latest-only i lifecycle eksportu/notyfikacji.
- `src/ntfy_notifications.py` — bezpieczny asynchroniczny klient ntfy.
- Testy `tests/test_comparison_resolution_options.py`, `test_comparator_gui_and_options.py`, `test_export_live_preview.py`, `test_export_preview.py`, `test_ntfy_notifications.py`, `test_nvidia_modern_pipeline.py`, `test_padding_d3d_config.py`, `test_playback_speed_resolution.py` oraz testy sąsiednich ścieżek regresji.

## Testy i odtworzenie pomiarów

- `python -m pytest -q` — **172 passed, 2 skipped** (12,10 s).
- `python -m compileall -q src tests` — zaliczone.
- Pełne rzeczywiste eksporty A/D, preview off/on oraz cztery krótkie MP4 rozdzielczości sprawdzono na RTX 5070 Ti; wszystkie zakończyły się kodem 0 i poprawną walidacją.
- Polecenia uruchamiające cały pomiar A/B ASS i podglądu: `python work/benchmark_comparator_features.py`.
- Polecenia uruchamiające warm-up i dwa przebiegi dla każdego rozmiaru Dual 4K: `python work/benchmark_dual4k_dimensions.py`.
- Dokładne polecenia FFmpeg dla każdego zarejestrowanego wariantu, łącznie z rzeczywistymi ścieżkami tymczasowych ASS i parametrami, zapisano w [RAPORT_COMPARATOR_BENCHMARK_COMMANDS.json](RAPORT_COMPARATOR_BENCHMARK_COMMANDS.json). Wyniki źródłowe benchmarków pozostają też w `work/ass-benchmark/results.json`, `dual4k-results.json` i `ffprobe-padding-results.json`.

## Ograniczenia

- Wydajność zależy od sterownika, temperatury, obciążenia i materiału źródłowego. Wartości są pomiarami tego komputera i tej pary plików.
- 8K benchmark mierzył 3000 klatek bez audio, aby odizolować ścieżkę wideo; pełne 8K 31-minutowe MP4 nie było kodowane. Wymiary pełnego 8K potwierdzono krótkimi plikami 30-klatkowymi przez FFprobe.
- Pełny 4K preview był pomiarem MP4 z audio. Preview ogranicza się do 2 próbek/s, a GUI odświeża najwyżej co 0,5 s; to podgląd kontrolny, nie odtwarzanie każdego eksportowanego frame'u.
- Krótkie testy pikseli potwierdzają czarne pasy i wymiary. Nie wykonano subiektywnego porównania każdego pola ASS z referencyjnym renderem poza zachowaniem bieżącego grafu i testami wyjściowymi.
- Dwa testy automatyczne są oznaczone jako skipped przez istniejące warunki środowiskowe.
