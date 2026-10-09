```text
BASELINE_GPU=NVIDIA GeForce RTX 5070 Ti
BASELINE_DRIVER=610.88
BASELINE_FPS=46.94003
BASELINE_WALL_TIME=16.77339 s proces / 15.97783 s native
BASELINE_CPU=0.942% wszystkich 32 logicznych CPU
BASELINE_GPU_3D=6.057%
BASELINE_GPU_ENCODE=94.684%
BASELINE_GPU_DECODE=18.325%
BASELINE_GPU_COPY=0.013%
```

# RAPORT ASYNC GPU EXPORT PIPELINE — 7 października 2026

Wdrożono ring osobnych zasobów GPU i rzeczywiste completion events NVENC. Oryginalny Direct API13.0: **46.94 FPS**, finalny ASYNC **48.08 FPS (+2.42%)**. Wymuszony developerski SYNC: **36.29 FPS**, ASYNC szybszy o **32.49%**. To dwa różne porównania.

P6 jest ograniczony używanym silnikiem NVENC: Windows PDH mierzy 94.68% przed i 96.25% po zmianie dla PID exportera. API zgłosiło dwa NVENC. Odczyt nvidia-smi około 50% nie dowodził zapasu pojedynczego używanego silnika. P6 nadal osiąga około 48–49 FPS, ponieważ ta sesja nasyca NVENC.

**Globalnego PASS nie przyznano:** P400, Intel QSV i AMD AMF nie są dostępne do fizycznej walidacji. Historyczne około 48 FPS na P400 to informacja użytkownika, a nie powtórzony tutaj benchmark. Separacji RTX/P400 na identycznym materiale nie udowodniono.

## Warunki testu

- Źródła: `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4` i `GX010345.MP4`; oba HEVC 3840×2160, 30000/1001 FPS, źródłowa rotation 180°.
- Układ góra/dół, DJI nad GoPro, offset 3.232 s odtworzony z czasów overlay w Compare.mp4. Brak zapisanego pliku projektu; ten offset jest odtworzonym ustawieniem.
- Output 3840×2160, HEVC Main, 50 000 000 bit/s, quality/P6, telemetry i preview ON; rzeczywisty odbiornik QLocalServer. Audio BOTH do kontroli synchronizacji.
- Odczytane, niezmienione QSettings Comparator/Comparator: font 0.75, opacity 0.65, pad_to_4k=true. Przy treści 3840×2160 pad nie powiększa płótna. Oddzielnie sprawdzono pad dla treści 1920×1080.
- Short: 750 kolejnych klatek / 25 s materiału. FPS native zawiera drain/audio/trailer; FRAME_TOTAL_MS obejmuje pętlę wideo. Wall procesu obejmuje inicjalizację.
- Baseline: zachowana instrumentowana wersja sprzed przebudowy (`work/KomparatorGpuExporter.profile-baseline.exe`), z wymuszonym istniejącym Direct API13.0. Finalna NVIDIA domyślnie wybiera Direct API13.0 na obu generacjach GPU; FFmpeg pozostaje porównaniem developerskim.

## Gdzie znika około 20 ms

Oryginalny FRAME_TOTAL_MS avg=20.659. nvEncEncodePicture avg=15.232 ms/wywołanie; lock bitstreamu avg=0.024. Główne oczekiwanie CPU było w submit, nie w lock.

ASYNC: frame avg=20.053; submit=0.525; event wait/backpressure=14.388; rasteryzacja obu telemetry=4.047 ms/klatkę. CPU przygotowuje następne klatki podczas kodowania wcześniejszych; przy pełnych czterech slotach czeka na najstarszy wynik. Nasycony silnik wymaga tego backpressure.

Izolowany encoder P6 z powtarzanym GPU inputem po pierwszym composite nadal dawał około 49 FPS fazy wideo. To eksperyment diagnostyczny, nie benchmark zysku. Izolowane P2 dawało około 302 FPS fazy wideo; nie użyto zmiany presetu jako optymalizacji P6.

## Profiling finalnego ASYNC

CPU: suma danego etapu w każdej z 750 kolejnych iteracji, także zera, gdy etap nie wystąpił. Jednostka ms. Register odbywa się przy init, audio po pętli wideo.

| STAGE | AVG | MEDIAN | P90 | P99 | MAX | N |
|---|---:|---:|---:|---:|---:|---:|
| FRAME_TOTAL_MS | 20.0535 | 20.1931 | 20.5461 | 20.7678 | 22.0313 | 750 |
| DECODE_VIDEO1_SUBMIT_MS | 0.2569 | 0.2531 | 0.4545 | 0.7293 | 1.8130 | 750 |
| DECODE_VIDEO1_WAIT_MS | 0.0030 | 0.0027 | 0.0058 | 0.0094 | 0.0670 | 750 |
| DECODE_VIDEO2_SUBMIT_MS | 0.1925 | 0.2001 | 0.2745 | 0.3912 | 1.1535 | 750 |
| DECODE_VIDEO2_WAIT_MS | 0.0032 | 0.0030 | 0.0050 | 0.0118 | 0.0909 | 750 |
| COMPOSITOR_MS | 0.0093 | 0.0083 | 0.0112 | 0.0215 | 0.1163 | 750 |
| TELEMETRY_RENDER_MS | 4.0472 | 3.9984 | 5.3127 | 6.7487 | 9.2462 | 750 |
| TELEMETRY_UPLOAD_MS | 0.1074 | 0.1084 | 0.1311 | 0.1809 | 0.3647 | 750 |
| GPU_COPY_MS | 0.0178 | 0.0166 | 0.0228 | 0.0412 | 0.0641 | 750 |
| NVENC_REGISTER_MS | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 750 |
| NVENC_MAP_MS | 0.0258 | 0.0208 | 0.0257 | 0.0394 | 3.3422 | 750 |
| NVENC_ENCODE_SUBMIT_MS | 0.5251 | 0.5112 | 0.5650 | 0.7408 | 1.1762 | 750 |
| NVENC_WAIT_MS | 14.3877 | 14.4676 | 16.8539 | 17.6795 | 17.9730 | 750 |
| NVENC_LOCK_BITSTREAM_MS | 0.0033 | 0.0028 | 0.0056 | 0.0074 | 0.0402 | 750 |
| NVENC_UNLOCK_MS | 0.0006 | 0.0005 | 0.0008 | 0.0013 | 0.0018 | 750 |
| NVENC_UNMAP_MS | 0.0326 | 0.0265 | 0.0366 | 0.2660 | 0.4822 | 750 |
| MUX_VIDEO_MS | 0.0940 | 0.0531 | 0.2001 | 0.2832 | 2.2899 | 750 |
| PREVIEW_READBACK_MS | 0.0211 | 0.0002 | 0.0006 | 0.6828 | 0.9018 | 750 |
| D3D11_FLUSH_MS | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 750 |
| D3D11_QUERY_WAIT_MS | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 750 |
| D3D11_QUERY_POLL_MS | 0.0115 | 0.0108 | 0.0151 | 0.0281 | 0.0531 | 750 |
| OTHER_CPU_MS | 0.3144 | 0.3023 | 0.4435 | 0.6516 | 0.9203 | 750 |
| MUX_AUDIO_MS (faza/wywołanie) | 469.0089 | 469.0089 | 469.0089 | 469.0089 | 469.0089 | 1 |
| OUTPUT_DISK_WRITE_MS (faza/wywołanie) | 0.0992 | 0.0937 | 0.1348 | 0.1831 | 1.8091 | 606 |

DECODE_*_WAIT_MS mierzy CPU w receive_frame, nie aktywny czas NVDEC. Zwracane są powierzchnie D3D11; oba submit są krótkie, bez per-input CPU GPU-wait. Decode ma zapas. Nie dodano niepotrzebnych threads/queues decode.

### GPU timestamps

D3D11_QUERY_TIMESTAMP + TIMESTAMP_DISJOINT; odroczony GetData(DONOTFLUSH), bez busy-wait. Disjoint próbki są odrzucane. Pending queries <=256; liczba próbek też ograniczona. Na końcu unresolved_gpu_queries=0.

| GPU bracket | AVG | MEDIAN | P90 | P99 | MAX | N |
|---|---:|---:|---:|---:|---:|---:|
| COMPOSITOR_GPU_MS | 11.4883 | 14.1903 | 15.4653 | 17.6265 | 18.0104 | 750 |
| TELEMETRY_UPLOAD_GPU_MS | 1.8068 | 0.0347 | 11.7071 | 16.9775 | 18.0143 | 1404 |
| GPU_COPY_GPU_MS | 0.0517 | 0.0515 | 0.0530 | 0.0698 | 0.0761 | 750 |

GPU bracket obejmuje planowanie i zależności strumienia poleceń; nie jest wyłącznie aktywnym czasem kernela VP. W ASYNC dłuższe przedziały composite/upload zawierają kolejkę. Nie sumowano ich do czasu CPU. NVENC/NVDEC są osobnymi silnikami: aktywność z PDH, completion NVENC z eventów SDK.

## Zmiany i lifecycle

- Slot ma własną NV12 texture, registered/mapped resource, bitstream buffer, event, PTS i stan. Register raz przy init; unmap po completion i odebraniu bitstreamu.
- FREE → COMPOSITING/copy → SUBMITTED → BITSTREAM_READY → copy packet/unlock/unmap → FREE. Debug assert pilnuje stanu. Pakiet ma osobną własność CPU, więc mux nie utrzymuje slotu GPU.
- Odbiór ASYNC po wypełnieniu ring. Blokujący wait przy pełnej puli i EOS. Async wykrywany przez NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT; fallback init do API sync. Brak warunku po nazwie karty.
- Bez eventów: bounded queue, poprawny blokujący lock przy odzyskiwaniu slotu/drain. Test NVENC_DISABLE_ASYNC_EVENTS=1 przeszedł na RTX; nie zastępuje to fizycznego testu Pascala.
- Jeden compositor output pozostaje: uporządkowany immediate-context VRAM copy oddaje obraz do osobnej texture slotu. NVENC czyta wyłącznie slot, więc output nie jest jego in-flight zasobem. GPU copy około 0.05 ms nie był bottleneckiem. Dodatkowa pula compositor targets nie miała uzasadnienia pomiarowego.
- Kolejność odbioru buforów zgodna z SDK; PTS z outputTimeStamp. Zachowano istniejące frameIntervalP=1 (I/P, bez B). DTS=PTS poprawne dla tej konfiguracji. Nie usuwano B-frames jako optymalizacji.
- Cancel sprawdzany przed SendFrame, po wait na wolny slot i przed encode submit. Niesubmitowana klatka odrzucana; przyjęte frames drainowane, audio ograniczone do ich czasu, AAC flushowane, trailer zapisany.
- Osobny EOS event. Błędy przerywają drain; cleanup: unlock, unmap, unregister events/resources, destroy buffers/encoder, release textures.

[Kontrakt SDK 13.0: async, kolejność i zasoby](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html). [Limit pojedynczej sesji do wydajności jednego NVENC](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html). Nie wymuszono split-frame ani zmiany jakości/presetów/bitrate.

## Synchronizacje — przegląd

| Miejsce | Rola po zmianie |
|---|---|
| EncodePicture | nieblokujący submit async; pomiar około 0.525 ms |
| Map/Unmap | osobny slot; unmap po completion |
| RegisterResource | raz na slot przy init; zero rejestracji per-frame |
| WaitForSingleObject | poll(0), pełna pula i drain; timeout zamiast niekończącej się pętli |
| Lock/UnlockBitstream | gotowy wynik; API sync używa blocking lock dopiero przy odzyskiwaniu slotu |
| D3D11 Flush | brak jawnego per-frame Flush w exporterze |
| GetData | profiling/preview DONOTFLUSH; brak while(GetData==S_FALSE) |
| Preview Map | DO_NOT_WAIT; skip niezgotowanej aktualizacji |
| Preview IPC | WaitForMultipleObjects/timeout w CPU worker, bounded queue i try_lock |
| avcodec_send_packet/receive_frame | zmierzone decode; brak przebudowy |
| QSV/AMF send_frame/receive_packet | istniejący FFmpeg backend + profiling; hardware niedostępny |
| Mux/AVIO | małe sync zapisy, poniżej 1% budżetu; bez nowego mux thread |
| Mutex | brak globalnego lock decode→composite→encode→mux; D3D protection pozostaje |
| Python/stdout | QProcess readyReadStandardOutput; progress co 200 ms, 5/s |

## Depth i presety

Macierz kontrolna: te same źródła, LR/offset0, font1.0/opacity1.0, 4K/50 Mbps/overlay i rzeczywiste preview ON. Każda para SYNC/ASYNC ma identyczne ustawienia. Główny baseline powyżej używa zapisanych opcji GUI. Nie uznano zmiany fontu ani presetu za zysk pipeline.

| Depth | FPS |
|---:|---:|
| 1 | 46.664 |
| 2 | 48.045 |
| 3 | 47.911 |
| 4 | 47.975 |
| 6 | 47.867 |
| 8 | 47.699 |
| 12 | 47.790 |

Default 4: stabilne długie runy, rekomendowany pool przy braku B, brak istotnego zysku z 6–12. Benchmark pozwala dobrać depth na innym GPU; nie ma kosztownego autotuningu przy każdym eksporcie.

| Preset | SYNC FPS | ASYNC FPS | Gain |
|---|---:|---:|---:|
| Najszybszy/P2 | 69.290 | 111.739 | 61.26% |
| Zbalansowany/P4 | 53.261 | 115.972 | 117.74% |
| Najlepsza/P6 | 33.717 | 47.975 | 42.29% |

W speed/balanced najaktywniejszy wątek zajmował około 91% jednego CPU; telemetry staje się kolejnym limitem powyżej 110 FPS. Przy P6 CPU ma zapas. Zachowano rasteryzację i outline.

## CPU / VRAM / IO / preview

Najaktywniejszy TID: 29.70% jednego logicznego CPU; native CPU global 1.021%. Render, submissions decode/encode i mux video są na głównym wątku, hardware i IPC preview asynchroniczne.

| TID | CPU user+kernel [s] | % jednego CPU / wall procesu |
|---:|---:|---:|
| 2300 | 4.8438 | 29.70 |
| 33504 | 0.3594 | 2.20 |
| 22228 | 0.1250 | 0.77 |
| 6236 | 0.0312 | 0.19 |
| 34644 | 0.0156 | 0.10 |
| 16124 | 0.0156 | 0.10 |

PDH dedicated VRAM dla PID: 1218.109 → 1253.633 MiB, +35.523 MiB, około trzech dodatkowych input textures 4K NV12. DXGI CurrentUsage peak=1233.598 MiB — inny licznik; nie mieszano go z baseline PDH.

Finalny normalny build bez profilera: 7193 klatek / 240 s materiału, 147.490 s procesu, 49.014 FPS. Po 30 s warmup VRAM 1253.637–1253.637 MiB; RSS 398.684–418.051 MiB, średnio początek/koniec okna 409.330/412.579 MiB. Brak wykrytego niekontrolowanego narastania pamięci. Profiling przechowuje ograniczone próbki; ocenę normalnego builda wykonano bez niego.

OUTPUT_WRITE_MBPS w JSON: **megabit/s**, 81.059 Mb/s = 10.132 MB/s względem native wall. OUTPUT_DISK_WAIT_MS=60.132 ms łącznie. Hook rzeczywistego AVIO write_packet mierzy powrót zapisu do systemu/cache; nie wymusza fizycznego flush/fsync. Brak fsync/flush-to-disk per-frame; IO nie ograniczało eksportu.

Preview A/B (kontrolny top/bottom, font1.0): OFF=48.119, ON=48.026 FPS; koszt 0.192%. 960×540, staging3, nonblocking Map; render thread wait count=0. Główny short miał 25 thumbnaili, aktualny long 240. Checkboxa nie dodano.

## Obraz, MP4, cancel i stabilność

- Reprezentatywne klatki 0/30/150/300/600/749, decode RGB960×540: baseline/ASYNC i SYNC/ASYNC identyczne pikselowo, MAE=0. Pad SYNC/ASYNC również identyczne. To próbki, nie checksum wszystkich klatek pełnego filmu.
- Pasy RGB mean=0/0/0, p99=0. Outline self-test: white glyph, black outline, transparent background PASS; rysowanie zachowane.
- Pakiety: 750 short, 7193 long240, 10790 long360. PTS/DTS krok1001 przy timebase1/30000, monotoniczne, bez dziur/duplikatów.
- Raw MP4 tkhd matrices identity, brak output rotation side data; źródła odwrócone180 obracane na GPU, upright pixels.
- Short: video25.025 s / AAC25.002667 s, start0; long240: video240.006433 / AAC240.0 s. Rozbieżność poniżej klatki. Offset/delay audio zachowany.
- Finalny cancel async: 122 klatki, HEVC4.070733 / AAC4.070729 s; fallback bez events: 123, HEVC4.104100 / AAC4.104104 s. MP4 zachowane i czytelne, exit2, counters0/0/0.
- Błąd compositora frame40 z in-flight frames: exit1 w1.49 s, bez hang; cleanup i usunięcie output zgodnie z dotychczasowym error policy.
- Długie runy: 360 s materiału /223 s procesu /48.55 FPS; 240 s /ponad146 s procesu /około49.1 FPS; aktualne opcje GUI /240 s /49.014 FPS. Brak błędów decode/encode/mux, narastania kolejki i deadlocków.

## Trace

CSV/JSON pierwszych300 frames. ENCODE_IN_FLIGHT to submit→completion zaobserwowane przez odbiorcę; zawiera kolejkę/opóźnienie odbioru. MUX_PACKET używa rzeczywistego frame PTS. SYNC peak1, ASYNC peak4, późniejsze decode/composite/submit zachodzą podczas posiadania wcześniejszych inputów przez encoder.

![Timeline](C:/Users/adram/Documents/Codex/2026-10-07/files-pasted-by-the-user-pracujemy/outputs/export_pipeline_timeline.png)

## Pola końcowe

```text
ROOT_BOTTLENECK=HEVC P6 / pojedynczy nasycony NVENC; CPU oczekiwał w EncodePicture, shared input i API sync ograniczały overlap
ASYNC_PIPELINE_IMPLEMENTED=YES — input resource ring + completion events
IN_FLIGHT_FRAME_COUNT=4
RING_BUFFER_DEPTH=4
RTX5070TI_FPS_BEFORE=46.94003
RTX5070TI_FPS_AFTER=48.07549
RTX5070TI_GAIN_PERCENT=2.419
P400_FPS_BEFORE=N/A, historyczne ~48 od użytkownika nie powtórzone
P400_FPS_AFTER=N/A, brak sprzętu
SYNC_FPS=36.28596
ASYNC_FPS=48.07549
ASYNC_GAIN_PERCENT=32.491
CPU_AFTER=1.021% native/global
MAX_CPU_THREAD_USAGE=29.701% jednego CPU, maksimum średnich TID/wall
VRAM_BEFORE_MB=1218.109 MiB dedicated PID
VRAM_AFTER_MB=1253.633 MiB dedicated PID
PREVIEW_OFF_FPS=48.11898
PREVIEW_ON_FPS=48.02649
PREVIEW_COST_PERCENT=0.192
FULL_FRAME_HWDOWNLOAD_COUNT=0
FULL_FRAME_HWUPLOAD_COUNT=0
SOFTWARE_VIDEO_FRAME_COUNT=0
BLACK_PADDING_PASS=PASS
OVERLAY_PASS=PASS
AUDIO_PASS=PASS
TELEMETRY_PASS=PASS
SYNC_PASS=PASS
ORIENTATION_PASS=PASS
GRACEFUL_CANCEL_PASS=PASS
2_MINUTE_STABILITY_PASS=PASS
MEMORY_LEAK_PASS=PASS, brak wykrytego niekontrolowanego wzrostu w opisanych runach
DEADLOCK_PASS=PASS
FINAL_BOTTLENECK=P6 — nasycony używany NVENC; speed/balanced — CPU telemetry
FINAL_STATUS=RTX_TESTS_PASS; FULL_ACCEPTANCE_NOT_GRANTED — P400/QSV/AMF sprzętowo niezweryfikowane
GPU_3D_AFTER=6.210%
GPU_ENCODE_AFTER=96.245%
GPU_DECODE_AFTER=18.664%
GPU_COPY_AFTER=0.017%
```

## Acceptance i ograniczenia

Na RTX zweryfikowano realne in-flight GPU resources, trace overlap, brak per-frame Flush/busy wait, bounded queues, zero-copy, HEVC, obraz, orientację, padding, audio/cancel oraz ponad2 min ciągłego eksportu. Nie zmieniono presetów, bitrate, output FPS/rozdzielczości i nie pomijano klatek.

**Niewykonane:** P400/driver582.78, Intel QSV i AMD AMF. Probes QSV/AMF nie mogły uruchomić właściwego hardware; dostępna NVIDIA i Remote Display Adapter. API13.0 zachowane; fallback na RTX sprawdzony. Fizycznego testu P400 i pełnego acceptance PASS to nie zastępuje.

Zakres dowodowy: brak saved project (layout/offset odtworzone z Compare); sześć próbek obrazu; GPU timestamps przedziałów kolejki, nie izolowanych kernelów; IO callback zapisu do systemu/cache, nie fizycznego fsync.

## Build i reprodukcja

Zmiany w K:\GoPro\Comparator: NvencDirectEncoder, HwEncoder, ExportPipeline, AudioMuxer; profiling decode/compositor/telemetry i DXGI memory; nowy PipelineProfile.h. Python GUI/opcje nie były zmieniane.

- tools/benchmark_async_gpu_export.py: native/QProcess, działające preview, PDH engines/memory, CPU TIDs, depths/presets/cancel/long.
- tools/verify_async_gpu_export.py: pakiety, audio, raw matrices, sampled RGB compare i padding.
- EXPORT_PROFILE=<prefix>: stats avg/median/p90/p99/max + trace CSV/JSON. Normalny build nie tworzy szczegółowych samples ani GPU queries.
- Developerskie PIPELINE_MODE=SYNC|ASYNC, NVENC_RING_DEPTH=1..12, NVENC_DISABLE_ASYNC_EVENTS=1, EXPORT_FFMPEG_NVENC=1. EXPORT_ISOLATE_ENCODER=1 jawnie oznacza powtarzany input diagnostyczny; nie jest normalnym exportem.

```powershell
cmake -S . -B work/build-async -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build work/build-async -j 4
python tools/benchmark_async_gpu_export.py --config work/current_project.json --output-dir work/p400_benchmark --quick
python tools/benchmark_async_gpu_export.py --config work/current_project.json --output-dir work/normal_check --normal-only --long-seconds 240
```

Na innym komputerze poprawić paths źródeł w config i porównywać identyczny materiał/parametry. Oba helpery Release są identyczne, SHA256:

2C59576EBC9ECE03750B36397B641D2B98CAB09B9D4AB2008DBE7B8B294B3150

Przed zmianą zachowano sources w work/async_pipeline_backup oraz oba oryginalne exe w work/. Logi/config/MP4: work/*_verification; macierz: work/async_verification. Materiały użytkownika pozostają niezmienione. Kopia raportu jest też w root projektu.
