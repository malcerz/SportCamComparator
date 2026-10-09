# Comparator — podgląd eksportu 5 FPS i rozdzielczość dopasowana do okna

Data pomiarów: 8 października 2026 r.  
Komputer: NVIDIA GeForce RTX 5070 Ti, compute capability 12.0.  
Źródła: `K:\GoPro\2026-10-06\GX010345.MP4` i `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4`, oba 3840×2160 z rzeczywistą telemetrią oraz obrotem Display Matrix −180°.

## Zmiana podglądu

Podgląd nadal jest próbką końcowego kompozytu z tego samego procesu eksportu. Gałąź dzieli wynik po korekcie orientacji, dwóch nakładkach ASS, stacku i dopełnieniu, więc pokazuje prawidłowy cały obraz, napisy i czarne pasy. Nie uruchamia drugiego dekodowania ani renderowania, nie tworzy dużego pliku tymczasowego i nie koduje ponownie HEVC.

Przy rozpoczęciu eksportu Comparator odczytuje faktyczny rozmiar widgetu obrazu podglądu, po odjęciu paska statusu i przycisku Anuluj. Wybiera największy mieszczący się rozmiar z poziomów 640×360, 960×540, 1280×720 i maksymalnie 1600×900. Zachowuje aspect ratio kompozytu, nie powiększa ponad wymiary źródłowe i dobiera parzyste wymiary. Dla rzeczywistego obszaru 1973×844 wybrany został obraz 1280×720. Przy zmianie wielkości okna Qt skaluje aktualną klatkę z KeepAspectRatio i SmoothTransformation; FFmpeg nie jest restartowany.

Próbki wideo powstają z częstotliwością 5 fps, a GUI sprawdza najnowszą klatkę co 200 ms. Bufor przechowuje najwyżej najnowszy kompletny JPEG; starsze obrazy są zastępowane zamiast tworzyć kolejkę opóźnionych klatek.

## Większe JPEG-y i nieblokujący transport

UDP został zastąpiony lokalnym strumieniem TCP loopback. TCP przenosi JPEG-y większe niż limit datagramu i zachowuje kolejność bajtów; odbiornik składa kompletne klatki po markerach JPEG SOI/EOI. Bufor strumienia ma limit 10 MiB, pojedynczy JPEG limit 8 MiB. Klatki uszkodzone, niekompletne albo ponad limit są odrzucane. FFmpeg wysyła gałąź przez asynchroniczny muxer FIFO z `queue_size=2` i `drop_pkts_on_overflow=1`, więc wolniejszy odbiornik nie zatrzymuje enkodera.

Test protokołu przesłał wieloklatkowy strumień JPEG-ów powyżej 65 KB, również pociętych na fragmenty TCP. Parser skleił poprawne obrazy i wyświetlił najnowszą klatkę. W realnych pomiarach C/D wszystkie oczekiwane próbki dotarły, bez uszkodzonych klatek i bez strat transportu. Różnica między odebranymi a wyświetlonymi klatkami wynika z zastępowania starszych próbek przez najnowszą.

## Metoda A/B

Wykonałem cztery warianty sekwencyjnie, bez konkurującego FFmpeg: po 300 klatek warm-up i dwa pomiary po 3000 klatek (około 100 sekund materiału na przebieg). Każdy wariant używał tych samych klipów, CUDA/NVDEC, `scale_cuda`, `hwdownload`, orientacji, dwóch rzeczywistych ASS, stacku, kompozytu 3840×2160 z dopełnieniem, HEVC NVENC p4, 10 Mbit/s i 29,97 fps. Wyjście wideo kierowałem do `NUL`, aby mierzyć przepustowość.

| Wariant | Średnie FPS | Czas / przebieg | Zmiana względem A | FFmpeg speed (1 / 2) | CPU procesu* | GPU / NVENC / NVDEC | Peak RSS | Peak VRAM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A: Bez podglądu | 134.61 | 22.29 s | +0.00% | 4.56x / 4.57x | 450% | 16.6% / 46.5% / 59.8% | 1925 MiB | 3531 MiB |
| B: 320×180, 2 fps (stare parametry) | 134.71 | 22.27 s | -0.07% | 4.56x / 4.58x | 453% | 17.2% / 46.3% / 61.8% | 1990 MiB | 3532 MiB |
| C: 1280×720, 5 fps | 134.16 | 22.36 s | +0.34% | 4.56x / 4.54x | 466% | 17.1% / 45.2% / 58.0% | 2150 MiB | 3536 MiB |
| D: 1600×900, 5 fps | 133.20 | 22.52 s | +1.05% | 4.49x / 4.55x | 496% | 17.2% / 45.4% / 58.6% | 2249 MiB | 3576 MiB |

* CPU to procent jednego logicznego rdzenia procesu FFmpeg; np. 450% oznacza średnio około 4,5 rdzenia. Monitorowane próbki pochodziły z `psutil` i `nvidia-smi`. Narzut FPS wyniósł **0,34%** dla 1280×720 i **1,05%** dla 1600×900. Oba są poniżej celu 5%; wariant D pozostał w granicach celu, więc nie było potrzeby automatycznego zmniejszania próbek. Profil B mierzy stare parametry 320×180/2 fps na nowym TCP, aby odseparować wpływ jakości/częstotliwości od problemu granic datagramu. Historyczny pełny eksport poprzedniej implementacji UDP wyniósł 139,92 fps bez podglądu i 139,33 fps z nim; to osobny, dłuższy pomiar i nie jest łączony z tą serią.

### Próbki, ruch i opóźnienie

| Profil | Odebrane | Wyświetlone | Zastąpione starsze | Odrzucone/uszkodzone | Dane TCP | Średni JPEG | Opóźnienie odbiór→GUI: średnie / maksymalne |
|---|---:|---:|---:|---:|---:|---:|---:|
| B | 400 | 209 | 191 | 0 | 0.88 MiB | 2.3 KiB | 45.2 / 125.5 ms |
| C | 1000 | 213 | 787 | 0 | 19.35 MiB | 19.8 KiB | 19.8 / 192.6 ms |
| D | 1000 | 215 | 785 | 0 | 28.52 MiB | 29.2 KiB | 22.2 / 201.4 ms |

Przy 1280×720 GUI wyświetliło około 106 klatek z 500 na przebieg; przy 1600×900 około 107–108. Eksport przetwarza wideo około 4,5 raza szybciej niż czas materiału, dlatego w 22-sekundowym pomiarze próbki 5 fps w czasie filmu docierały częściej niż 5 klatek na sekundę zegarową. GUI wyświetlało średnio około 5 najnowszych próbek na sekundę, a starsze pomijało. Maksymalny zmierzony czas od kompletnego odbioru do pokazania wyniósł około 201 ms.

Kodowanie JPEG nie udostępnia w tym grafie niezależnego licznika CPU. Szacowałem zatem dodatkowy koszt CPU całej gałęzi (skalowanie, MJPEG i transport) przez różnicę użycia CPU procesu względem A:

| Profil | CPU procesu | Różnica do A | Szacowany dodatkowy CPU na próbkę |
|---|---:|---:|---:|
| B | 453% | +3 p.p. | 3.2 ms/frame |
| C | 466% | +16 p.p. | 7.2 ms/frame |
| D | 496% | +46 p.p. | 20.6 ms/frame |

To przybliżenie, nie izolowany czas samego kodera. Wzrost peak RSS względem A wyniósł około 65 MiB dla B, 226 MiB dla C i 325 MiB dla D. Peak VRAM wzrósł najwyżej o 45 MiB.

## Rzeczywisty eksport z okna głównego

Uruchomiłem eksport przyciskiem w Comparatorze dla standardowego 2160p i Dual 4K z dopełnieniem. Każdy test wyprodukował 90 klatek; FFprobe sprawdził rozdzielczość MP4, a widget odbierał strumień TCP i wyświetlał podgląd.

| Tryb | Video widget | Próbka | Odebrane | Wyświetlone | Zastąpione | Odrzucone | Opóźnienie średnie | FFprobe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2160p | 1973×882 | 1280×720 | 15 | 5 | 10 | 0 | 54.7 ms | 3840×2160 / 90 kl. |
| dual4k_pad | 1973×882 | 1280×720 | 15 | 10 | 5 | 0 | 43.4 ms | 7680×4320 / 90 kl. |

Podczas testów testowano także anulowanie i przywrócenie playera przez automatyczne testy cyklu eksportu; gniazdo TCP oraz named pipe są zamykane przy kończeniu podglądu.

## Zmienione pliki

- `src/export_live_preview.py` — dobór rozmiaru, timer 200 ms, parser TCP z limitami oraz liczniki.
- `src/main.py` — pobranie rozmiaru rzeczywistego widgetu obrazu i przekazanie wymiarów do eksportu.
- `src/nvidia_modern.py`, `src/export_prepare.py` — próbkowanie 5 fps, skala, wyjście MJPEG/TCP i asynchroniczne FIFO.
- `native/KomparatorGpuExporter/Config.h`, `Config.cpp`, `ExportPreview.h`, `ExportPreview.cpp`, `ExportPipeline.cpp` — konfiguracja rozmiaru i odstępu próbkowania podglądu D3D11.
- `tests/test_export_live_preview.py`, `tests/test_nvidia_modern_pipeline.py` — testy timeru, wymiarów, TCP/JPEG >65 KB i grafu.
- `work/benchmark_comparator_features.py`, `work/benchmark_preview_5fps.py`, `work/verify_mainwindow_preview_5fps.py` — benchmark i test integracyjny okna.

## Walidacja

- `python -m pytest -q`: **177 passed, 2 skipped**.
- `python -m compileall -q src tests work/benchmark_comparator_features.py work/benchmark_preview_5fps.py work/verify_mainwindow_preview_5fps.py`: zaliczone.
- Helpery D3D11 przebudowane przez `build_gpu_exporter.ps1` i `build_gpu_exporter_nvidia_compat.ps1`; capability probe zaliczony.
- Wszystkie polecenia FFmpeg użyte w rozgrzewkach i pomiarach A–D znajdują się w [RAPORT_COMPARATOR_PREVIEW_5FPS_COMMANDS.json](RAPORT_COMPARATOR_PREVIEW_5FPS_COMMANDS.json). Wyniki liczbowe i próbki metryk są w `work/ass-benchmark/preview-5fps-results.json`; test okna w `work/ass-benchmark/mainwindow-preview-5fps-results.json`.

Wyniki zależą od sterownika, temperatury, obciążenia i źródeł. Benchmark A–D mierzył 3000 klatek do `NUL`; osobna integracja GUI potwierdziła 90-klatkowe pliki dla obu rozdzielczości. Gdy eksport przetwarza materiał szybciej niż GUI może go odświeżyć, podgląd celowo pomija starsze klatki, zachowując priorytet szybkości zapisu MP4.
