# Comparator: rozdzielczość i przyspieszenie eksportu

## Zmiany

- `src/main.py`: kontrolka głównego paska ma teraz etykietę „Przyspieszenie filmu” i wartości ×1/×2/×4. Nie wybiera ani nie zmienia rozdzielczości. Opcja rozdzielczości jest zapisywana oddzielnie w Opcjach.
- `src/options_dialog.py`: rozdzielczości to `2160p` (zawsze płótno 3840×2160) i `dual4k` (3840×4320 góra/dół lub 7680×2160 lewo/prawo). Usunięto checkbox dopełniania. Poprzednie `4k_uhd` migruje do `dual4k`; stare wartości skali nie są interpretowane jako szybkość.
- `src/export_prepare.py`: po offsetach, tpad/trim, ASS i złożeniu obrazu wykonywane jest jedno `setpts`, a potem próbkowanie do stałego FPS. Czas przekazywany do FFmpeg i paska postępu wynosi długość kompozytu podzieloną przez szybkość. Standardowe płótno zawsze ma 3840×2160; nieobsługiwany rozmiar kodera kończy się czytelnym błędem bez automatycznego zmniejszenia.
- `src/nvidia_modern.py`: zachowano NVDEC → `scale_cuda` → `hwdownload` → filtry CPU → stack → HEVC NVENC p4. Zmiana czasu i FPS działa w tym samym grafie. Dual4k nadal wymaga pozytywnego probe i używa `-split_encode_mode forced` wyłącznie w ścieżce NVIDIA Modern.
- `src/video_encoder.py`: dodano cache’owaną, jednoramkową próbę kodera dla dokładnego rozmiaru; Opcje sprawdzają wybrany koder bez uruchamiania benchmarku.
- `src/i18n.py` oraz testy aktualizują etykiety i nowe zachowanie. Dodano brakujące małe MP4 `tests/artifacts/tone440.mp4` i `tone880.mp4`, wymagane przez istniejące testy eksportu.

## Czas, FPS, audio i nakładki

FPS wyznaczam jako najwyższy poprawny `avg_frame_rate` z obu wejść; dla brakującej lub niepoprawnej wartości biorę `r_frame_rate`, a ostatecznie 30 FPS. Wyjściowy FPS jest ograniczony do 60. Filtr `fps` po `setpts` utrzymuje tę samą częstotliwość przy ×2/×4, odrzucając klatki zamiast podnosić wynik do 120/240 FPS. W ten sposób VFR jest próbkowane do jawnego CFR.

Audio najpierw przechodzi dotychczasową selekcję, synchronizację i miks. Potem ×2 używa `atempo=2`, ×4 używa `atempo=2,atempo=2`; końcowy `atrim` dopasowuje audio do czasu obrazu. Mute nie mapuje audio. ASS jest renderowane przed zmianą czasu na osi źródłowej, więc obraz i nakładki przyspieszają razem tylko raz.

Dla szybkości większej niż ×1 eksport używa grafu FFmpeg i wybranego kodera zamiast helpera D3D11. Pozwala to wykonać jedną rekompresję ze zmianą PTS, stałym FPS i audio `atempo`; nie ma dodatkowego przebiegu po gotowym MP4. Eksport D3D11 przy ×1 pozostaje na dotychczasowej ścieżce.

## Podwójne 4K i możliwości kodera

Dla CPU sprawdzany jest `libx265` przez jedną czarną klatkę zakodowaną do dokładnego rozmiaru wyjściowego. Na tym komputerze test zakończył się powodzeniem dla 3840×2160, 7680×2160 i 3840×4320. Dla NVIDIA Modern wymagane są test Modern i test układu z wymuszonym split encode. Pozostałe ścieżki NVIDIA, AMD i Intel sprawdzają docelową rozdzielczość wybranym koderem. Do Dual4k wymagane są również dwa źródła 3840×2160. Negatywny test wyłącza tę opcję i wyjaśnia przyczynę.

Przykładowe polecenie probe CPU dla lewo/prawo:

```text
K:\GoPro\Comparator\bin\ffmpeg.exe -hide_banner -loglevel error -nostdin -f lavfi -i color=c=black:s=7680x2160:r=1 -frames:v 1 -an -c:v libx265 -f null -
```

Analogiczny test dla góra/dół używa `s=3840x4320`.

## Rzeczywista weryfikacja RTX 5070 Ti

GPU: NVIDIA GeForce RTX 5070 Ti, compute capability 12.0. Wygenerowałem dwa 10-sekundowe źródła 3840×2160 / 30 FPS z audio i wykonałem eksporty przez aplikacyjny FFmpeg, `NVIDIA_MODERN_FFMPEG`, HEVC NVENC p4, bitrate 20 Mbps, audio `both`. FFprobe odczytał zgodne czasy formatu, wideo i audio:

| Profil | ×1 | ×2 | ×4 | FPS wyjścia |
|---|---:|---:|---:|---:|
| 2160p, 3840×2160 | 10,0 s | 5,0 s | 2,5 s | 30/1 |
| Podwójne 4K, 7680×2160 | 10,0 s | 5,0 s | 2,5 s | 30/1 |

Każda z trzech szybkości w danym profilu zachowała identyczne wymiary. Audio miało taki sam czas jak wideo. Każdy wariant Podwójnego 4K zawierał `-split_encode_mode forced`.

Średnie FPS raportowane przez końcową linię FFmpeg przy tych rzeczywistych, pełnych eksportach (z hstack/pad, audio i muxem):

| Profil | ×1 | ×2 | ×4 |
|---|---:|---:|---:|
| 2160p | 124 fps | 111 fps | 67 fps |
| Podwójne 4K lewo/prawo | 119 fps | 77 fps | 43 fps |

To wynik całej ścieżki eksportu na próbkach 4K, a nie izolowany benchmark NVENC; wynik zależy od zawartości, filtrów i audio. Dla porównania test rzeczywistym CPU `libx265`, ×4, potwierdził MP4 3840×2160 i 7680×2160 o długości 2,5 s i 30 FPS. Czas kodowania wyniósł odpowiednio 2,9 s i 4,6 s.

Pełne polecenia wygenerowane i uruchomione są zapisane wraz z FFmpeg output w `work/speed_resolution_validation/2160p_x*.log` i `dual4k_x*.log`. Dwa rzeczywiste polecenia ×4:

**2160p ×4:**

```text
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\Comparator\work\speed_resolution_validation\camera_a.mp4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\Comparator\work\speed_resolution_validation\camera_b.mp4 -filter_complex [0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=10.0,trim=duration=10.0[v0];[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=10.0,trim=duration=10.0[v1];[v0][v1]hstack=inputs=2,pad=3840:2160:(3840-iw)/2:(2160-ih)/2:black[composite];[composite]setpts=(PTS-STARTPTS)/4,fps=30[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=10.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=10.0[a1];[a0][a1]amix=inputs=2:duration=longest,atempo=2,atempo=2,atrim=duration=2.5[a] -map [v] -map [a] -c:a aac -fps_mode cfr -r 30 -c:v hevc_nvenc -preset p4 -b:v 20M -metadata:s:v:0 rotate=0 -t 2.5 K:\GoPro\Comparator\work\speed_resolution_validation\2160p_x4.mp4
```

**Podwójne 4K ×4:**

```text
K:\GoPro\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe -y -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\Comparator\work\speed_resolution_validation\camera_a.mp4 -hwaccel cuda -hwaccel_output_format cuda -i K:\GoPro\Comparator\work\speed_resolution_validation\camera_b.mp4 -filter_complex [0:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=10.0,trim=duration=10.0[v0];[1:v]scale_cuda=format=nv12,hwdownload,format=nv12,setpts=PTS-STARTPTS,null,tpad=start_mode=clone:start_duration=0.0:stop_mode=clone:stop_duration=10.0,trim=duration=10.0[v1];[v0][v1]hstack=inputs=2[composite];[composite]setpts=(PTS-STARTPTS)/4,fps=30[v];[0:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=10.0[a0];[1:a]asetpts=PTS-STARTPTS,adelay=0.0:all=1,apad,atrim=duration=10.0[a1];[a0][a1]amix=inputs=2:duration=longest,atempo=2,atempo=2,atrim=duration=2.5[a] -map [v] -map [a] -c:a aac -fps_mode cfr -r 30 -c:v hevc_nvenc -preset p4 -b:v 20M -split_encode_mode forced -metadata:s:v:0 rotate=0 -t 2.5 K:\GoPro\Comparator\work\speed_resolution_validation\dual4k_x4.mp4
```

## Testy i ograniczenia

- `pytest -q`: **142 passed, 2 skipped**.
- `python -m compileall -q src tests`: powodzenie.
- Macierz testowa obejmuje 12 kombinacji rozdzielczości × układu × szybkości; dodatkowe testy sprawdzają audio mute/left/right/both, położenie ASS, FPS, migrację ustawień i CPU.
- Rzeczywiste FFprobe potwierdziło wszystkie sześć wariantów RTX dla obu rozdzielczości oraz CPU ×4 dla obu płócien.
- Nie można zagwarantować Dual4k na każdej karcie. Decyduje próba dokładnego rozmiaru kodera; użycie CPU przy Podwójnym 4K może być wolne i wymaga odpowiedniej pamięci.
