# Raport: naprawa orientacji w Comparatorze

## Przyczyna

Comparator wcześniej usuwał orientację z metadanych wyjściowych przez `-metadata:s:v:0 rotate=0`, ale własne grafy `filter_complex` nie wykonywały jawnej korekty pikseli. Nakładka ASS była poprawna, bo jej pozycje liczono w zwykłym układzie obrazu; sam materiał wideo z metadanymi obrotu −180° pozostawał odwrócony. W ścieżce Modern własny graf CUDA/CPU nie może polegać na domyślnej autorotacji FFmpeg.

Oba dostarczone wejścia z `K:\GoPro\2026-10-06\` mają 3840×2160, nie mają `tags.rotate`, a FFprobe zwraca `Display Matrix` z `rotation=-180`. To potwierdziło, że sprawdzanie wyłącznie tagu `rotate` nie wystarcza.

## Wykrywanie i decyzja

Nowy wspólny moduł `src/video_orientation.py` odczytuje `side_data_list` / Display Matrix, w tym pole `rotation` i tekstową macierz FFprobe. Macierz ma pierwszeństwo przed starszym `tags.rotate`; tag jest fallbackiem, gdy macierzy nie ma. Macierz nietypowa, nieczytelna, nieortogonalna albo kąt inny niż wielokrotność 90° powoduje ostrzeżenie i brak zgadywanej korekty.

Dla każdego wejścia logowane są `INPUT_ROTATE_TAG`, `INPUT_DISPLAYMATRIX_ROTATION` i `INPUT_ORIENTATION_DECISION`. Znormalizowane wejścia dostają `-metadata:s:v:0 rotate=0`. Jeśli choć jedna orientacja jest nieznana/nietypowa, program nie deklaruje jej jako znormalizowanej i nie dodaje wymuszonego `rotate=0`.

## Mapowanie i miejsce korekty

Wszystkie ścieżki wejściowe mają `-noautorotate`, a Comparator sam stosuje korektę przed ASS, `tpad`, `trim`, stackowaniem i końcową zmianą PTS/FPS:

| Obrót Display Matrix | Korekta pikseli |
|---|---|
| 0° | brak (`null`) |
| +90° | `transpose=cclock` |
| 180° lub −180° | `hflip,vflip` |
| 270° lub −90° | `transpose=clock` |

NVIDIA Modern zachowuje `scale_cuda → hwdownload → format=nv12`; obrót odbywa się po pobraniu klatek na CPU i przed ASS, bez ponownego uploadu CUDA. Dla ćwierćobrotu obraz jest dopasowany z zachowaniem proporcji do płótna danej kamery przed ASS.

Wspólny builder Legacy/CPU/AMD/Intel stosuje tę samą decyzję oraz własny etap `[orient_fixN]`. D3D11 otrzymuje jawne kąty z tej samej analizy FFprobe; ustawienie trafia do rotacji strumieni kompozytora przed nałożeniem telemetrii.

## Zmienione pliki

- `src/video_orientation.py`
- `src/export_prepare.py`
- `src/nvidia_modern.py`
- `native/KomparatorGpuExporter/Config.h`
- `native/KomparatorGpuExporter/Config.cpp`
- `native/KomparatorGpuExporter/DemuxerDecoder.h`
- `native/KomparatorGpuExporter/ExportPipeline.cpp`
- `tests/test_video_orientation.py`

Zbudowano również `bin/KomparatorGpuExporter.exe` oraz NVIDIA-compat `bin/KomparatorGpuExporterNvidia.exe`.

## Testy i walidacja

- `pytest -q`: **156 passed, 2 skipped**.
- `python -m compileall -q src tests`: zakończone bez błędów.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_gpu_exporter.ps1 -Clean`: natywny helper zbudowany, capability probe zaliczony.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_gpu_exporter_nvidia_compat.ps1`: helper NVIDIA zbudowany.
- Testy jednostkowe pokrywają brak obrotu, 90°, 180°, 270°, fallback taga, nieznaną macierz, konflikt źródeł metadanych i dwa wejścia z różnymi orientacjami. Symulacja wejścia Quadro P400 z `rotation=-180` wybiera `hflip,vflip` przed ASS.
- Pełny `prepare_export` na RTX 5070 Ti wykrył dla obu rzeczywistych plików `rotation=-180`, wybrał `NVIDIA_MODERN_FFMPEG` i wygenerował eksport HEVC NVENC p4: 75 klatek / 2,5 s, 3840×2160. FFprobe wyjścia nie znalazł tagu ani side data rotacji; log kodera podaje `rotate: 0`. Klatka kontrolna jest pionowo poprawna, a testowa nakładka ASS pozostaje u góry obrazu.
- Bezpośredni eksport natywnym helperem D3D11 z tymi samymi wejściami także dał obraz pionowo poprawny w 3840×2160; FFprobe nie znalazł rotacji w wyjściu.
- Dodatkowy fixture z Display Matrix +90° przeszedł przez Modern z `transpose=cclock`, zakończył się poprawnie w 3840×2160 i wyjściowym `rotate=0`.

Pliki walidacyjne pozostawiono w `K:\GoPro\Comparator\work\orientation_validation\` (log Modern, wyjścia Modern/D3D11 oraz klatki kontrolne).

## Przykładowe polecenie FFmpeg po poprawce

Przykład dla dwóch wejść z macierzą −180°, układ góra/dół, standardowe wyjście 2160p. W produkcji `null` może być zastąpione wygenerowanym filtrem ASS; istotne jest, że ASS jest za `[orient_fixN]`.

```powershell
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y `
  -noautorotate -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\GX010345.MP4 `
  -noautorotate -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4 `
  -filter_complex "[0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,hflip,vflip[orient_fix0];[orient_fix0]setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0:stop_mode=clone:stop_duration=2.5,trim=duration=2.5[v0];[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,hflip,vflip[orient_fix1];[orient_fix1]setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0:stop_mode=clone:stop_duration=2.5,trim=duration=2.5[v1];[v0][v1]vstack=inputs=2,pad=3840:2160:(3840-iw)/2:(2160-ih)/2:black[composite];[composite]setpts=PTS-STARTPTS,fps=29.97[v]" `
  -map "[v]" -fps_mode cfr -r 29.97 -c:v hevc_nvenc -preset p4 `
  -metadata:s:v:0 rotate=0 -t 2.5 wynik.mp4
```

