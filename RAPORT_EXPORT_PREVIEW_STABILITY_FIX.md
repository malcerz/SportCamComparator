# Naprawa eksportu i stabilności podglądu

Data: 2026-10-05. Praca na źródłach SportCamComparator.
Katalog nie zawiera `.git`; nie inicjalizowano repozytorium ani nie commitowano binarek.
Istniejące EXE/DLL/OBJ nie stanowiły podstawy diagnozy. Native budowany od zera.

## Przyczyny i zmiany

1. `src/main.py`: brak `Path` i `re` uniemożliwiał eksport / obsługę progress. Dodano importy; statyczna analiza pyflakes nie wykazuje niezdefiniowanych nazw.
2. QProcess: konsumowanie stdout usuwało przyczynę błędu. Log jest zachowywany przed parsowaniem; fragmenty linii są składane pomiędzy odczytami, końcówka odczytywana przy finished. Podłączono started, errorOccurred, readyReadStandardOutput, finished. FailedToStart kończy zadanie bez czekania na finished; crash i inne błędy są zapamiętane. Raport GUI obejmuje backend, exit code/status, process error, komunikat native i końcówkę logu. D3D11 wymaga NormalExit, kodu 0, complete/success i braku zarejestrowanego błędu.
3. `ExportPipeline.cpp`: dawniej `break` po compositor/encoder prowadził do flush/audio/trailer/success. Teraz jawne failed/failureReason, sprawdzanie dekoderów, overlay, encodera, odbioru pakietów, muxera, audio i trailera. Błąd zamyka output bez trailera sukcesu i usuwa częściowy plik, return 1. Cancel usuwa plik, return 2. Success wyłącznie po całym pipeline. Test diagnostyczny wymusza awarię po zapisaniu 15 klatek.
4. `DemuxerDecoder`: błąd odróżniony od EOF; EOF zachowuje ostatnią sprzętową klatkę. Przed początkiem źródła używana pierwsza klatka. Eksport kończy się na global duration, nie EOF jednego źródła.
5. Zachowano AVRational źródła, encoder framerate i odwrotne time_base; PTS klatki = jej indeks, duration pakietu = 1 przed rescale. ffprobe potwierdza avg_frame_rate i r_frame_rate `30000/1001`.
6. GPU compositor zachowuje proporcje i respektuje rotację źródła. Na tym AMD rotacja 180 przez VideoProcessorSetStreamRotation powodowała błąd Blt; dwie sprzętowe operacje mirror realizują ją poprawnie. Bez mapowania video do RAM.

## Podgląd i wspólna oś czasu

Stary mechanizm: positionChanged player1 -> _sync_12 -> seek player2, gdy drift przekraczał 300 ms; shared seekbar odnosił się do player1. Usunięto cały ten mechanizm i zbiorcze disconnect signalów.

Nowy `src/preview_sync.py`: QElapsedTimer, global position i playing. `delay1=max(0,-offset)`, `delay2=max(0,offset)`, pozycja = T-delay, global duration = max(delay1+duration1, delay2+duration2). Ta matematyka obowiązuje preview, video export i audio. Dla +4423 ms film2 pozostaje paused na pierwszej klatce; rozpoczyna play raz po przekroczeniu granicy, bez kolejnych seeków na 0. Shared seek wykonuje po jednym seeku na każdą stronę. Indywidualny seek/frame-step zapisuje nowy offset wraz z żądaną pozycją, zanim Qt potwierdzi asynchroniczny seek; późniejsze wczytanie telemetrii nie nadpisuje ręcznej korekty.

Soft sync: normalnie 1.0; błędy 60–250 ms -> 0.98/1.02; większe -> 0.95/1.05, histereza przy powrocie do obszaru zgodności. Awaryjny seek dopiero po 8 kolejnych pomiarach >1500 ms, odstęp co najmniej 5 s. `KOMPARATOR_DEBUG_SYNC=1` drukuje global T, actual/target/error/rate i hard_seek_count raz/s. Zegar nie wynika z nieregularnych positionChanged.

`PlayerWidget.set_overlay` porównuje tekst i zmienia tylko label/visibility/size. Layout wyłącznie resize lub realna zmiana native size; cache font/padding. Test 100 różnych TIME potwierdza 0 layout rebuildów.

Dodatkowy realny blocker: raster QGraphicsView/QGraphicsVideoItem z dwoma dużymi 4K HEVC powodował wielosekundowe przerwy pętli GUI (w pomocniczym teście zegar przeszedł z 7.4 do 47.3 s). Użyto natywnego QVideoWidget oraz lekkiego QLabel jako dziecka powierzchni video. Nie wprowadzono mapowania pełnych klatek w Pythonie. Zmiana jest ograniczona do renderera podglądu. Wykrywanie GPU teraz uwzględnia rzeczywiste nazwy adapterów, ponieważ lista encoderów FFmpeg błędnie wybierała Intel QSV na komputerze AMD.

Liczba seeków PRZED: NOT_MEASURED w pełnym porównywalnym biegu starego kodu; stary kod wymuszał seek po każdym przekroczeniu 300 ms. Wyniku nie wywnioskowano z binarki. Pomiar PO: 0 hard seeków i 0 wywołań set_position przez 300.993 s.

## Telemetria i przygotowanie eksportu

Stary D3D11 path budował tekstowy event dla każdej przyszłej klatki (TIME uniemożliwiał scalanie) w GUI, w katalogu projektu. Usunięto również nieużywany helper extract_telemetry_events.

Nowy `src/export_prepare.py`: worker wykonuje probe, ffprobe, serializację kompaktowych próbek / generowanie ASS dla Legacy. D3D11 config w systemowym tempfile zawiera camera, start_datetime i [timestamp, ISO, exposure]. Nie zawiera TIME, tekstowych eventów ani ASS. Native binary search wybiera najbliższą próbkę, tekst jest tworzony podczas renderowania. DATE używa czasu najbliższej próbki, jak istniejące overlay GoPro/DJI; TIME używa aktualnej pozycji źródła. Font GDI cache; Unicode przez DrawTextW. Przesyłana wyłącznie mała bitmapa overlay z osobnymi licznikami uploadu.

Diagnostyczne odtworzenie rozmiaru starego configu dla dostępnych nagrań: **19 993 853 B** i **128 209 eventów**, nowy **4 802 028 B**. Odtworzenie starej generacji poza aplikacją: 0.936 s na tej maszynie. Żadne z tych eventów nie powstaje w aktualnej ścieżce eksportu.

GoPro `telemetry_mp4.read_track_payload`: seek do gpmd/gpmf samples z stsz/stsc/stco/co64/stts/ctts/elst; nie skanuje video. Istniejący parse_gpmf bez zmian. Dla nieobsługiwanego MP4 log `GPMF_NATIVE_UNSUPPORTED -> FFmpeg fallback`. Obsługa cancel. Realny GX010338: old/native **46 959 608 B**, raw identyczny, parser identyczny, **63 960** identycznych TelemetrySample, wszystkie timestamp/ISO/exposure/datetime/camera, overlay 0/1/5.57/60/300/1000 s identyczny. Czas starej ekstrakcji 0.572 s, native 0.542 s przy cache dysku; nie deklarujemy sztucznego dużego przyspieszenia. Korzyścią jest brak subprocess pełnej ekstrakcji w normalnej ścieżce.

DJI wire/parser nie zmieniano. Wskazany `DJI_20260928064217_0001_D.MP4` nie istnieje. Użyto `D:\GoPro\DJI_20261002062647_0003_D.MP4`: DJI Osmo Action 6, **64 091** próbek, zachowane wartości. Regresje syntetyczne DJI pozostają w unittest.

## Audio i sprzęt

AudioMuxer ma audio-only libavfilter z amovie posiadającym niezależne input/decode contexts. asetpts/aresample/adelay/apad/atrim/amix -> AAC. MUTE nie tworzy ścieżki, LEFT/RIGHT wybierają właściwą stronę wraz z delay, BOTH rzeczywiście miksuje. Nie użyto software video filter graph w native exporterze. NOPTS ciszy adelay rozwiązano za pomocą jawnego audio sample clock, bez przesuwania dekodera video. Sprawdzane wszystkie zapisy, trailer i flush.

Test dwóch różnych wejść: 440 Hz (8 s) / 880 Hz (4 s), +4.423 s. LEFT amplituda 440 ~0.1245, RIGHT 880 ~0.1250 po delay, wcześniej 0. BOTH po delay 440 ~0.0623 i 880 ~0.0624, wcześniej drugi ton nieobecny. Wygenerowany MP4 trwa cały global timeline mimo EOF krótszego źródła. Ujemny offset także testowany.

Sprzęt: **AMD Radeon (TM) Graphics**. Probe otwiera rzeczywisty wybrany encoder/codec/resolution, inicjalizuje hardware frames context i alokuje hardware frame. AUTO fallback Legacy po failed probe, forced D3D11 pokazuje błąd. Realny encoder: h264_amf / hevc_amf. NVENC i QSV: **NOT_TESTED**, brak tych GPU.

## Build i dowody

Czysty `.\build_gpu_exporter.ps1 -Clean`, MSVC **19.44.35228.0**, Visual Studio BuildTools 17.14, x64, CMake **4.4.2**, Ninja, FFmpeg **9.0.1-full_build-www.gyan.dev**, avcodec/avformat/avutil/avfilter oraz D3D11. Skrypt sprawdza pełną ścieżkę przed czyszczeniem build. Szczegóły build w `tests/artifacts/clean_build.log`.

Dowody: `tests/artifacts/native_matrix_results.json`, logi poszczególnych procesów, MP4 i JSON configów, `unittest.log`, `telemetry_comparison.json`, `config_size_comparison.json`, `preview_benchmark.json`, zrzuty klatek PNG. Test Qt offscreen wchodzi przez MainWindow.export_video, mockuje dialog zapisu, uruchamia rzeczywisty QProcess i weryfikuje plik. Osobne testy FailedToStart, crash, podzielony JSON, type:error z kodem 0 oraz brak complete z kodem 0. Legacy ma osobny test wejścia przez GUI.

Wizualna kontrola realnego eksportu: poprawny nieuszkodzony obraz obu źródeł, zachowane proporcje/rotacja; lewo MISSION 1, prawo DJI Osmo Action 6. Na T=6.006 s TIME źródła2=1.583 s przy offset4.423. Odczyt ISO/EXP odpowiada właściwym próbom. Kontrola 10-sekundowych MP4 w obu kolejnościach przez ffprobe i dekodowanie klatek.

Usunięto stare wygenerowane src/_ass_temp_komp/overlay1.ass i overlay2.ass. .gitignore: _ass_temp_komp, __pycache__, build, bin i *.obj. Brak binarnych commitów.

Zmienione źródła: src/main.py, src/player_widget.py, src/preview_sync.py (nowy), src/export_prepare.py (nowy), src/video_encoder.py, src/telemetry_mp4.py, src/telemetry_gpmf.py, src/telemetry_gpmf_new.py, src/telemetry_factory.py; native Config.h/.cpp, ExportPipeline.h/.cpp, DemuxerDecoder.h/.cpp, HwEncoder.h/.cpp, AudioMuxer.h/.cpp, TelemetryRenderer.h/.cpp, GpuCompositor.h/.cpp, main.cpp; CMakeLists.txt, build_gpu_exporter.ps1, .gitignore; test_matrix_gpu_export.py, tests/test_export_preview.py (nowy), test_telemetry_dji.py, benchmark_preview.py, benchmark_export_start.py, diagnose_playback.py, verify_gpmf_native.py.

## Wyniki końcowe

Rzeczywisty pięciominutowy preview: **300.993 s**, hard seek count **0**, wszystkie set_position po początkowym seeku **[0,0]**, layout updates podczas playback **[0,0]**, Qt stalled events **[0,0]**. Klatki **[9024,8891]** (druga strona opóźniona 4.423 s). Średni absolute sync error **24.877 ms**, max **301 ms**. Max odstęp pomiarów timera 1 s: **1.062 s**. Qt nie wystawia bezpośredniego licznika dropped frames; podano rzeczywiście otrzymane videoFrameChanged i stalled, nie wymyślono liczby dropped.

CPU procesu (psutil, 100% oznacza jeden logiczny rdzeń): średnio **31.24%**, max **124.5%**. Bez telemetry load **30.4%**, podczas load **62.33%**, po load z overlay **29.40%**. Frame rate obu źródeł podczas ładowania **29.95/s**, po nim **29.98/s**. Wzrost CPU podczas parsowania nie spowodował okresowych seeków ani zatrzymania playback.

Test MainWindow z pełnymi 128 051 próbkami obu nagrań: klik -> rzeczywisty QProcess **0.397 s**, config **4 802 058 B**, największy odstęp pompowania GUI **0.162 s**. Normalna ścieżka GUI nie zawiera duration_limit_seconds. Rzeczywiste anulowanie native potwierdzone, częściowy output usunięty. Test Legacy wejścia przez MainWindow także PASS.

Finalna macierz na ostatnim czystym buildzie: **12/12 PASS**. Cztery audio modes z analizą widma; awarie compositor/encoder/input/output; HEVC top-bottom z offsetem -4.423 s; GoPro+DJI i DJI+GoPro po 10 s; dodatkowy HEVC **3840×2160** przez 3 s. Realny GoPro+DJI: **50.109 fps**, DJI+GoPro **54.988 fps**; 4K synthetic **57.056 fps**. Szybkości są zmierzone, dotyczą tych krótkich testów, nie całych 35 min.

Każdy udany proces spełnia download/upload/software video = **0/0/0**. W realnym 10 s eksporcie 468 uploadów małych overlay / 30 270 240 B. ffprobe: dokładne r_frame_rate i avg_frame_rate **30000/1001**, poprawny AAC oraz odtwarzalny MP4; pełny frame count potwierdza utrzymanie ostatniej klatki krótszego źródła.

Unittest **22/22 PASS** (4.985 s ostatniego biegu), compileall PASS, import main PASS, pyflakes PASS. Build PASS (10/10 etapów, od pustego build). Realna wizualna kontrola klatek T=0 i T=6 po finalnym buildzie PASS. Oryginalny wskazany plik DJI jest niedostępny; regresję sprawdzono na źródłowych testach DJI i drugim dostępnym nagraniu tej samej kamery. NVENC/QSV NOT_TESTED, nie przypisano im PASS.

PYTHON_IMPORTS_PASS=YES
MAINWINDOW_EXPORT_START_PASS=YES
QPROCESS_ERROR_REPORTING_PASS=YES

NATIVE_FAILURE_RETURNS_NONZERO=YES
NATIVE_FALSE_SUCCESS_FIXED=YES
PARTIAL_OUTPUT_REMOVED_ON_FAILURE=YES

D3D11_REALTIME_TELEMETRY=YES
D3D11_PREGENERATED_ASS=NO
D3D11_PER_FRAME_JSON_EVENTS=NO

GLOBAL_TIMELINE_PASS=YES
PREVIEW_4423MS_OFFSET_PASS=YES
PREVIEW_HARD_SEEK_COUNT=0
PREVIEW_PERIODIC_STUTTER_PASS=YES
OVERLAY_LAYOUT_REBUILD_PER_TICK=0

GOPRO_NATIVE_GPMF_PASS=YES
GOPRO_OVERLAY_REGRESSION_PASS=YES
DJI_TELEMETRY_REGRESSION_PASS=YES

AUDIO_MUTE_PASS=YES
AUDIO_LEFT_PASS=YES
AUDIO_RIGHT_PASS=YES
AUDIO_BOTH_REAL_MIX_PASS=YES
AUDIO_OFFSET_PASS=YES

FULL_FRAME_HWDOWNLOAD_COUNT=0
FULL_FRAME_HWUPLOAD_COUNT=0
SOFTWARE_VIDEO_FRAME_COUNT=0

REAL_GPU_ENCODER=h264_amf/hevc_amf
REAL_GPU_EXPORT_PASS=YES
REAL_EXPORT_FPS=50.109 (GoPro+DJI), 54.988 (DJI+GoPro)

UNIT_TESTS=22/22 PASS
COMPILEALL=PASS
FINAL_STATUS=PASS_ON_AVAILABLE_AMD_HARDWARE; NVENC/QSV_NOT_TESTED; REQUESTED_DJI_FILE_MISSING_ALTERNATIVE_TESTED

