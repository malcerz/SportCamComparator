# Raport: rozbieżność benchmarku NVIDIA Modern

Data: 2026-10-08. GPU: NVIDIA GeForce RTX 5070 Ti, compute capability 12.0. Materiały 3840×2160, 29,97 fps: `K:\GoPro\2026-10-06\GX010345.MP4` i `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4`.

## Wynik diagnozy

Ręczny wynik został odtworzony. Dokładny referencyjny graf w CMD uzyskał 223 fps i speed 7,44×. Ten sam argv uruchomiony przez Python z stderr do konsoli, pliku lub PIPE również uzyskał 223 fps. Benchmarkowany graf produkcyjnego buildera uzyskał w powtórce 221 fps zgłoszone przez FFmpeg i 217,58 FPS policzone przez Python. Nie ma więc obecnie różnicy 223 vs 106 fps ani dowodu na blokowanie procesu przez przechwytywanie stderr.

Znaleziono dwie rzeczywiste różnice. Po pierwsze, samo `ffmpeg.exe` z PATH wybiera `C:\ProgramData\chocolatey\bin\ffmpeg.exe` (FFmpeg 8.1.1 essentials), a benchmark przypina `K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe` (FFmpeg n8.1.2-21-gce3c09c101). Obie binarki uzyskały jednak ponad 200 fps na referencyjnym argv: wersja PATH podała 223 fps, a wersja repozytoryjna 217–223 fps zależnie od przebiegu. Różnica binarek nie tłumaczy dawnego wyniku 106 fps.

Po drugie, poprzedni benchmark budował graf przez produkcyjny builder: miał dodatkowe `setpts`, `null`, `tpad` i `trim`, nie miał `shortest=1` i kończył się mapą `[v]`; referencja ma prosty graf bez tych filtrów i mapuje `[out]`. To może zmieniać koszt grafu, ale w powtórzonym pomiarze zmieniło wynik tylko nieznacznie: 221 fps FFmpeg dla buildera wobec 223 fps referencji. W normalnym trybie benchmark nadal testuje produkcyjny graf. `--reference-command` jest diagnostycznym trybem odrębnym, nie zmienia eksportu.

Historycznego wyniku 106 fps nie można przypisać do jednej potwierdzonej przyczyny. Stary JSON zachował liczbę klatek i czas Pythona (3000 / 28,242 s), ale nie zachował końcowej statystyki FFmpeg `fps/speed` ani pełnego stderr. Nowe przebiegi nie powtórzyły takiej anomalii. Możliwy wpływ chwilowego obciążenia lub stanu wydajności GPU pozostaje hipotezą, a nie ustalonym faktem.

## Porównanie argumentów: referencja vs poprzedni benchmark

| Argument | Referencja | Poprzedni benchmark | Różnica |
|---|---|---|---|
| Plik FFmpeg | `ffmpeg.exe` z PATH w ręcznym CMD | jawnie `K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe` | różne pliki: PATH 8.1.1 essentials, harness n8.1.2-git; obie wersje przekroczyły 200 fps |
| Kolejność wejść | `[0] GX010345`, `[1] DJI_...0005_D` | historyczne polecenie benchmarku: `[0] DJI`, `[1] GX010345` | odwrócono; bez znaczącego wpływu: 3000 klatek dało 221 vs 217 fps FFmpeg |
| `-hwaccel cuda` | dwa razy, przed każdym `-i` | dwa razy, przed każdym `-i` | brak |
| `-hwaccel_output_format cuda` | dwa razy | dwa razy | brak |
| `scale_cuda` | `1920:1080:format=nv12` na obu wejściach | `1920:1080:format=nv12` na obu wejściach | brak dodatkowego skalowania |
| download i format | `hwdownload,format=nv12` na obu wejściach | `hwdownload,format=nv12` na obu wejściach | brak |
| `vstack` | `vstack=inputs=2:shortest=1` | `vstack=inputs=2` | referencja jawnie kończy na krótszym wejściu |
| Dodatkowe filtry | brak | `setpts=PTS-STARTPTS,null,tpad=...,trim=...` dla obu wejść | wyłącznie harness produkcyjnego grafu; nie występują w trybie referencyjnym |
| Mapowanie | `-map [out]` | `-map [v]` | etykieta grafu inna |
| Audio | `-an` | brak `-an`, ale jawne mapowanie samego wideo `[v]` | oba polecenia nie kodują audio |
| `-fps_mode` | `passthrough` | `passthrough` | brak; nie ma filtra `fps=60` ani innego dodatkowego `fps` |
| Koder / preset | `hevc_nvenc`, `p4` | `hevc_nvenc`, `p4` | brak |
| Bitrate | `10M` | `10M` | brak |
| ASS / pad / offset / synchronizacja | brak ASS, pad, opóźnienia | brak ASS i pad; opóźnienia wejść 0; builder normalizuje PTS i stosuje tpad/trim | produkcyjny graf ma obsługę PTS/długości, referencja jej nie ma |
| Null muxer | `-f null NUL` | `-f null NUL` | brak |
| Pozostałe opcje | `-hide_banner -benchmark -stats` | benchmark dodawał `-y` i `-metadata:s:v:0 rotate=0` | różnice nie dotyczą dekodowania ani kodowania obrazu |
| Limit | ręczne polecenie bez `-frames:v` | harness mierzył 3000 klatek | osobny test 3000/6000/brak limitu nie wykazał spadku FPS z limitem |

## Wyniki na RTX 5070 Ti

Wszystkie wyniki używają p4, 1920×2160, 29,97 fps wejścia, chyba że w tabeli podano inaczej. Python wallclock obejmuje uruchomienie, inicjalizację i zamknięcie procesu. FFmpeg FPS/speed/elapsed pochodzą ze stderr i są raportowane oddzielnie.

| Test | Wariant | Klatki | FFmpeg fps | speed | FFmpeg elapsed | Python elapsed / FPS | Peak RSS |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Dokładne polecenie z CMD, `ffmpeg.exe` z PATH, przerwane `q` po ok. 32 s | 7165 | 223 | 7,44× | 32,137 s | CMD; Python N/A | 3327,2 MiB |
| 2 | Referencyjny argv z Python, stderr drenujemy na konsolę, `q` po 25 s | 5675 | 223 | 7,44× | 25,427 s | 25,637 s / 221,36 | 3376,6 MiB |
| 3 | Referencyjny argv z Python, stderr do pliku, `q` po 25 s | 5688 | 223 | 7,44× | 25,490 s | 25,730 s / 221,07 | 3399,3 MiB |
| 4 | Referencyjny argv z Python, stderr PIPE i bieżące opróżnianie, `q` po 25 s | 5686 | 223 | 7,45× | 25,444 s | 25,638 s / 221,78 | 3387,6 MiB |
| A | Bez limitu klatek; wersja PATH 8.1.1, zatrzymane `q` po 25 s | 5667 | 223 | 7,43× | 25,422 s | 25,664 s / 220,82 | 3349,0 MiB |
| B | Referencja `-frames:v 3000`, PIPE / `capture_output=True` | 3000 | 217 | 7,24× | 13,807 s | 14,013 s / 214,09 | 3339,5 MiB |
| C | Referencja `-frames:v 6000` | 6000 | 223 | 7,44× | 26,909 s | 27,105 s / 221,36 | 3363,0 MiB |
| kolejność | Referencja, wejścia odwrócone DJI + GX, 3000 klatek | 3000 | 221 | 7,37× | 13,567 s | 13,766 s / 217,92 | 3363,5 MiB |
| 5 | Graf produkcyjnego buildera, warm-up 300 osobno, pomiar 3000 | 3000 | 221 | 7,35× | 13,597 s | 13,788 s / 217,58 | 3364,1 MiB |

Warianty konsola/plik/PIPE są zbliżone w granicach normalnej zmienności pomiaru; żaden nie zbliżył się do 106 fps. Python wallclock jest o około 0,2 s dłuższy od czasu `rtime` FFmpeg, co nie tłumaczy różnicy 2×. Ograniczenie 3000 klatek dało 217 fps, 6000 dało 223 fps, a przebieg bez limitu po 25 s dał 223 fps. Nie ma podstaw, by limit 3000 uznać za źródło spadku o połowę.

## Dual 4K

Po zakończeniu diagnozy 1920×2160 wykonano analogiczne porównanie top/bottom, p4, `scale_cuda=format=nv12`, `hwdownload`, `vstack`, `-fps_mode passthrough` i `-split_encode_mode forced`. Referencyjny graf z `shortest=1` uzyskał 79 fps FFmpeg, speed 2,62×, 3000 klatek w 38,209 s, Python 77,94 FPS / 38,492 s, peak RSS 4870,8 MiB. Graf buildera z dodatkowymi filtrami uzyskał 77 fps, speed 2,56×, 3000 klatek w 39,025 s, Python 76,34 FPS / 39,296 s, peak RSS 4884,5 MiB. Ręczne ~90 fps nie zostało w tej serii dokładnie odtworzone, ale wartości są zbliżone; pełna różnica z poprzedniego benchmarku 67 fps nie powtórzyła się.

## Środowisko i subprocess

- Benchmark uruchamia dokładnie `K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe`; wersja `n8.1.2-21-gce3c09c101-20260630`.
- Pierwsze `ffmpeg.exe` z PATH w CMD to `C:\ProgramData\chocolatey\bin\ffmpeg.exe`, wersja `8.1.1-essentials_build-www.gyan.dev`; potwierdzono, że obie wersje uzyskują ~220 fps na referencji.
- Working directory: `K:\GoPro\Comparator`; Python: `C:\Python\python.exe`; `CUDA_VISIBLE_DEVICES` nieustawione. PATH wskazuje również WinGet 8.0.1 i `C:\tools\ffmpeg.exe`, ale nie są wybierane przez jawny resolver benchmarku.
- Priorytet procesu Windows: Normal (`0x20`); affinity mask `0xFFFFFFFF`. Python `subprocess` nie ustawia `creationflags`, affinity ani priorytetu, więc używa domyślnych wartości dziedziczonych z procesu nadrzędnego.
- PIPE wykorzystuje `subprocess.run(capture_output=True)`, które opróżnia pipe w trakcie działania procesu. Testy kontrolne console/file/PIPE potwierdziły brak blokowania stderr.

## Polecenia i zmiany

Tryb referencyjny nie używa `nvidia_modern.build_command`; ręcznie składa argv identyczne z grafem referencyjnym. Polecenie, które benchmark wypisuje dla mierzonego przebiegu, jest dokładnym Windows command line przekazanym do uruchomienia FFmpeg. Wynik można zapisywać JSON-em. Przykładowe polecenia testowe (uruchomione sekwencyjnie):

```powershell
python tools\benchmark_nvidia_modern.py K:\GoPro\2026-10-06\GX010345.MP4 K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 --reference-command --stop-after 25 --stderr-mode pipe --json work\nvidia_modern_integration\diagnostic_ref_pipe.json
python tools\benchmark_nvidia_modern.py K:\GoPro\2026-10-06\GX010345.MP4 K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 --reference-command --frames 3000 --stderr-mode pipe --json work\nvidia_modern_integration\diagnostic_ref_3000_capture_output.json
python tools\benchmark_nvidia_modern.py K:\GoPro\2026-10-06\GX010345.MP4 K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 --reference-command --frames 6000 --stderr-mode pipe --json work\nvidia_modern_integration\diagnostic_ref_6000.json
python tools\benchmark_nvidia_modern.py K:\GoPro\2026-10-06\GX010345.MP4 K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 --reference-command --dual4k --frames 3000 --stderr-mode pipe --json work\nvidia_modern_integration\diagnostic_dual_reference.json
```

`--stderr-mode` obsługuje `console`, `file` i `pipe`; `--ffmpeg-exe` pozwala diagnostycznie wybrać konkretną binarkę. Zmiany dotyczą wyłącznie `tools/benchmark_nvidia_modern.py`, testów benchmarku i tego raportu. `src/nvidia_modern.py`, `src/export_prepare.py`, GUI, klasyfikacja CC i builder produkcyjny nie były zmieniane w tej diagnozie.

## Testy

Dodano testy jednostkowe sprawdzające argv referencyjne, oba warianty grafu, poprawne wstawianie limitów oraz parsowanie statystyk FFmpeg niezależnie od wallclock. Pełne `pytest -q --tb=short`: 94 passed, 2 skipped, 2 failed. Dwa błędy to istniejące testy eksportu, które wymagają nieobecnego `tests/artifacts/tone440.mp4`; testy zmian `tests/test_benchmark_nvidia_modern.py` oraz testy NVIDIA Modern: 31 passed. `compileall` dla źródeł benchmarku/testów przeszedł.
