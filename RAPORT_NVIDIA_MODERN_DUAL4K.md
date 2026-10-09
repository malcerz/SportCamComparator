# Raport: NVIDIA Modern i tryb 2×4K

Data testu: 2026-10-08. Komputer: GeForce RTX 5070 Ti, sterownik 610.88, Windows WDDM. Materiały: `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4` i `K:\GoPro\2026-10-06\GX010345.MP4`, oba 3840×2160 HEVC.

## Wprowadzone zmiany

- `src/nvidia_modern.py` – cache capability probe’ów, obliczenie rozmiaru GPU scale, budowanie komendy produkcyjnej oraz poprawne cytowanie polecenia dla Windows.
- `src/export_prepare.py` – w AUTO dla NVIDIA najpierw sprawdzany jest Modern; po niepowodzeniu działa dotychczasowa hierarchia D3D11/Legacy/CPU. Wymuszone D3D11 i Legacy omijają Modern. Tryb 2×4K wymaga NVIDIA, AUTO, Modern i pozytywnego probe’u rozdzielczości.
- `src/main.py` – opcja „2×4K” pojawia się po pozytywnym probe’ie źródła i kodera dla bieżącego presetu/układu. Probe działa poza wątkiem GUI. Zmiana GPU/backendu/układu/presetu odświeża dostępność; po utracie obsługi zaznaczenie wraca do x1 z komunikatem. Błąd Modern zapisuje połączony log FFmpeg wraz z pełną komendą do pliku obok eksportu (`*.ffmpeg.log`).
- `src/backend_benchmark.py` – benchmark NVENC jawnie przekazuje preset, Balanced = `-preset p4`.
- `tools/benchmark_nvidia_modern.py` – pomiar produkcyjnego grafu CUDA decode → scale_cuda → hwdownload → CPU filters → stack → NVENC; osobny proces warm-up i osobny pomiar minimum 3000 klatek, z pomiarem elapsed/FPS/speed/RSS.
- `tests/test_nvidia_modern_pipeline.py` oraz aktualizacja `tests/test_universal_export_backends.py` – testy grafu, wymiarów, presetów, bitrate’u, fallbacku, blokady 2×4K i testy wcześniejszej hierarchii.

## Wykrywanie i wybór backendu

`resolve_legacy_ffmpeg("NVIDIA")` nadal wybiera FFmpeg z `runtime\nvidia\ffmpeg\` przed systemowym FFmpeg. Na tym komputerze użyty plik to `K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe`.

Modern nie opiera się na nazwie karty ani samym spisie filtrów. Generacja jest odczytywana najpierw przez `nvidia-smi --query-gpu=name,compute_cap`, a w Windows w razie potrzeby przez CUDA Driver API (`nvcuda.dll`). Compute capability < 7.5 oznacza LEGACY (Pascal/Maxwell i starsze), a >= 7.5 oznacza MODERN (Turing i nowsze). Brak wiarygodnej wartości CC bezpiecznie klasyfikuje kartę jako LEGACY; log podaje `NVIDIA_GPU_NAME`, `NVIDIA_COMPUTE_CAPABILITY`, `NVIDIA_ARCH_CLASS` oraz `NVIDIA_MODERN_REASON` wraz ze źródłem. Sama architektura nie wystarcza: Modern wymaga jednocześnie `MODERN_ARCHITECTURE && MODERN_FFMPEG_PROBE_PASS`. Probe wykonuje dekodowanie prawdziwej pierwszej klatki wejścia przez CUDA, `scale_cuda`, `hwdownload`, konwersję NV12 i inicjalizację `hevc_nvenc -preset p4`; p4 jest wymagany także wtedy, gdy GUI ma p2/p6. Następnie probe sprawdza wybrany preset. Wynik jest buforowany wg pliku źródłowego (ścieżka/rozmiar/mtime), FFmpeg i presetu. Dodatkowy probe 2×4K uruchamia rzeczywisty jedną-klatkowy encode z `hevc_nvenc`, wybranym presetem i `-split_encode_mode forced` w wymaganym rozmiarze; cache jest osobny dla układu i presetu.

W logu pojawiają się `NVIDIA_MODERN_PROBE=PASS/FAIL`, `NVIDIA_DUAL4K_PROBE=PASS/FAIL`, `EXPORT_BACKEND_SELECTED=NVIDIA_MODERN_FFMPEG`, opis grafu, `OUTPUT_SIZE`, a dla dual 4K także `NVIDIA_DUAL4K=1`, `NVIDIA_SPLIT_ENCODE=FORCED`. Pełna linia `FFMPEG_COMMAND` jest logowana i zapisywana w `*.ffmpeg.log`.

Fallback: w AUTO nieudany probe Modern przechodzi do istniejącej ścieżki eksportu; AMD/Intel/CPU nie zmieniły wyboru backendu. Wymuszony D3D11 nadal wymusza D3D11, a wymuszony Legacy pomija Modern. Gdy probe Modern przejdzie, ale samo FFmpeg zakończy się błędem, UI pokazuje backend, kod wyjścia i końcówkę stderr, a pełny log pozostaje przy pliku wyjściowym. Fallback po rozpoczęciu procesu nie jest wykonywany, żeby nie nadpisać częściowego pliku ani nie zmienić trybu 2×4K.

## Graf i rozmiary

Normalnie każde źródło ma `-hwaccel cuda -hwaccel_output_format cuda`; rozmiar `scale_cuda` jest wyliczany z wymiarów wejścia, układu, limitu dotychczasowego wyjścia 3840×2160 oraz x1/x0.5/x0.25. Dopiero po skalowaniu następuje `hwdownload,format=nv12`, a potem `setpts`, istniejący ASS, `tpad`, `trim`, stack i NVENC. Dla 4K x1 oznacza 1920×1080 na wejście, czyli 1920×2160 top/bottom albo 3840×1080 left/right przed `pad_to_4k`. Zwykłe `pad_to_4k` nadal daje 3840×2160.

W dual 4K wymagane są dwa wejścia 3840×2160; każde przechodzi przez `scale_cuda=format=nv12` bez zmiany rozmiaru, następnie download/CPU filters/stack. Rozmiar wynosi 3840×4320 top/bottom lub 7680×2160 left/right. Końcowe `pad_to_4k` jest pomijane z logiem `PAD_TO_4K_DISABLED_FOR_DUAL_4K`. `-split_encode_mode forced` trafia do polecenia wyłącznie dla dual 4K. Mute/left/right/both audio, AAC, offset, ASS, tpad, trim, bitrate GUI, p2/p4/p6 i `rotate=0` pozostają obsługiwane.

Poniższe przykłady wygenerował aktualny builder polecenia. Używają rzeczywistych plików, p4, 12 Mbps, obu ścieżek audio, testowego ASS, offsetu 250 ms dla drugiego wejścia; normalne przykłady mają włączone `pad_to_4k`, dual 4K celowo go pomija.

### Normalny top/bottom
```cmd
# OUTPUT_SIZE=3840x2160
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\GX010345.MP4 -filter_complex [0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=3.0,trim=duration=3.0[v0];[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.25:stop_mode=clone:stop_duration=3.0,trim=duration=3.0[v1];[v0][v1]vstack=inputs=2,pad=3840:2160:(3840-iw)/2:(2160-ih)/2:black[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=3.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=250.0:all=1,apad,atrim=duration=3.0[a1];[a0][a1]amix=inputs=2:duration=longest[a] -map [v] -map [a] -c:a aac -fps_mode passthrough -c:v hevc_nvenc -preset p4 -b:v 12M -metadata:s:v:0 rotate=0 -t 3.0 K:\GoPro\Comparator\work\example_top_bottom_normal.mp4
```

### Normalny left/right
```cmd
# OUTPUT_SIZE=3840x2160
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\GX010345.MP4 -filter_complex [0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=3.0,trim=duration=3.0[v0];[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.25:stop_mode=clone:stop_duration=3.0,trim=duration=3.0[v1];[v0][v1]hstack=inputs=2,pad=3840:2160:(3840-iw)/2:(2160-ih)/2:black[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=3.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=250.0:all=1,apad,atrim=duration=3.0[a1];[a0][a1]amix=inputs=2:duration=longest[a] -map [v] -map [a] -c:a aac -fps_mode passthrough -c:v hevc_nvenc -preset p4 -b:v 12M -metadata:s:v:0 rotate=0 -t 3.0 K:\GoPro\Comparator\work\example_left_right_normal.mp4
```

### 2×4K top/bottom
```cmd
# OUTPUT_SIZE=3840x4320
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\GX010345.MP4 -filter_complex [0:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=1.0,trim=duration=1.0[v0];[1:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.25:stop_mode=clone:stop_duration=1.0,trim=duration=1.0[v1];[v0][v1]vstack=inputs=2[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=1.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=250.0:all=1,apad,atrim=duration=1.0[a1];[a0][a1]amix=inputs=2:duration=longest[a] -map [v] -map [a] -c:a aac -fps_mode passthrough -c:v hevc_nvenc -preset p4 -b:v 12M -split_encode_mode forced -metadata:s:v:0 rotate=0 -t 1.0 K:\GoPro\Comparator\work\example_top_bottom_dual4k.mp4
```

### 2×4K left/right
```cmd
# OUTPUT_SIZE=7680x2160
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\GX010345.MP4 -filter_complex [0:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=1.0,trim=duration=1.0[v0];[1:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,ass=filename='K\:/GoPro/Comparator/work/nvidia_modern_integration/overlay.ass',tpad=start_mode=clone:start_duration=0.25:stop_mode=clone:stop_duration=1.0,trim=duration=1.0[v1];[v0][v1]hstack=inputs=2[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=1.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=250.0:all=1,apad,atrim=duration=1.0[a1];[a0][a1]amix=inputs=2:duration=longest[a] -map [v] -map [a] -c:a aac -fps_mode passthrough -c:v hevc_nvenc -preset p4 -b:v 12M -split_encode_mode forced -metadata:s:v:0 rotate=0 -t 1.0 K:\GoPro\Comparator\work\example_left_right_dual4k.mp4
```

## Wyniki weryfikacji

- Na RTX 5070 Ti Modern real-source probe przeszedł dla p2, p4 i p6. Probe dual 4K przeszedł dla top/bottom i left/right w każdym z tych presetów.
- Krótkie eksporty z rzeczywistych plików, ASS i audio both: normalny top/bottom i left/right (po 3 s) utworzyły HEVC 3840×2160 z AAC; dual top/bottom i left/right (po 1 s) utworzyły odpowiednio HEVC 3840×4320 i 7680×2160 z AAC. FFprobe odczytał kontenery poprawnie. To test inicjalizacji i integralności krótkich plików, nie pełny eksport całego materiału.
- Długi benchmark Modern p4 z tych samych materiałów, null muxer, bez audio/ASS/preview, warm-up 300 klatek wyłączony z pomiaru i osobny proces pomiaru 3000 klatek:
  - A, normalny top/bottom 1920×2160, split disabled: 28,242 s, 106,23 FPS, speed 3,544×, peak RSS 3390,9 MiB.
  - B, dual top/bottom 3840×4320, split forced: 44,624 s, 67,23 FPS, speed 2,243×, peak RSS 4884,2 MiB.
  - Ręczne punkty odniesienia wynosiły ~250/~90 FPS. Długi pomiar jest niższy o ~57,5% dla A i ~25,3% dla B; nie odtworzył ręcznych wyników. Wcześniejsze 300 klatek dawało 160,54/73,20 FPS. Różnice zachowujemy jako wynik pomiaru, bez ekstrapolowania ani deklarowania przyczyny.
  - Dokładne polecenia uruchomienia (Windows, katalog repozytorium; A i B należy odpalać sekwencyjnie):
    `python tools/benchmark_nvidia_modern.py K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 K:\GoPro\2026-10-06\GX010345.MP4 --layout top_bottom --preset balanced --warmup-frames 300 --frames 3000 --json work\nvidia_modern_integration\benchmark_normal_long.json`
    `python tools/benchmark_nvidia_modern.py K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 K:\GoPro\2026-10-06\GX010345.MP4 --layout top_bottom --dual4k --preset balanced --warmup-frames 300 --frames 3000 --json work\nvidia_modern_integration\benchmark_dual_tb_long.json`
- Testy po zmianach: pełny przebieg `pytest -q --tb=short` dał 90 passed, 2 skipped i 2 failed. Oba błędy pochodzą z istniejących testów eksportu zależnych od brakującego `tests/artifacts/tone440.mp4`; testy nie dochodzą do sprawdzanych ścieżek kodu. Zestaw dotyczący NVIDIA Modern, backendów uniwersalnych, GUI/opcji i dostępnych testów obsługi eksportu dał 62 passed, 1 skipped. Pominięty przypadek QSV wymaga sprzętu Intel, którego nie ma na tym komputerze. `compileall` zakończył się poprawnie.
- Stare testy inline preview/export zależne od brakujących plików testowych (`D:\GoPro\GX010338.MP4`, `tests\artifacts\tone440.mp4`) nie mogły zostać użyte jako regresja. Pozostałe testy UI i obsługi błędów eksportu zaliczone.

## Test klasyfikacji i ograniczenia

Test symulujący `Quadro P400 / Pascal / CC 6.1` potwierdził klasę LEGACY i zakończenie probe’u przed próbą FFmpeg, nawet gdyby FFmpeg umiał wykonać CUDA/NVDEC/scale_cuda/NVENC p4. Testy mapują RTX 20xx / CC 7.5, RTX 30xx / 8.6, RTX 40xx / 8.9 i RTX 50xx / 12.0 na MODERN. To test logiki na symulowanych danych; fizycznej P400 nie ma na tej maszynie. Karta testowa zgłosiła `NVIDIA GeForce RTX 5070 Ti`, compute capability 12.0, więc została sklasyfikowana jako MODERN.

Na tej maszynie nie ma dostępnego Intel QSV; nie wykonano sprzętowych regresji QSV, AMD AMF ani P400. Krótkie walidacje dual 4K sprawdziły utworzenie pliku, nie długi eksport, jego zachowanie przy anulowaniu ani maksymalną jakość wizualną. Benchmark Modern nie liczy disk/mux/audio/ASS, więc nie jest prognozą pełnego eksportu Comparatora. Dla dual 4K zmierzone ~73 FPS jest wynikiem tej konkretnej konfiguracji p4 i nie gwarantuje takiej samej szybkości na innych sterownikach, źródłach ani kartach.
