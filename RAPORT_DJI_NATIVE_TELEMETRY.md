# Raport DJI native telemetry — 2026-10-03

Zmiany wykonano w SportCamComparator. Nie zbudowano EXE. Dostarczony katalog nie miał `.git`, więc nie utworzono commita.

## Wynik i pliki

DJI i fabryka wykrywają MP4 natywnie w Pythonie. Nie używają ExifTool, Perla, subprocess, Google protobuf ani plików tymczasowych. GoPro zachowuje dotychczasowy parser i jego zależności FFmpeg/ffprobe.

- `src/telemetry_mp4.py`: odczyt MP4 przez seek, sample tables, offsety i timeline.
- `src/telemetry_dji_wire.py`: własny minimalny parser protobuf.
- `src/telemetry_dji.py`: provider, bisect, datetime, ISO, exposure, overlay i ASS.
- `src/telemetry_factory.py`: gpmd/gpmf → GoPro, djmd → DJI, brak → NullTelemetry.
- `src/telemetry_gpmf.py`: cofnięte opcjonalne color_temperature; logika GoPro niezmieniona.
- `tests/test_telemetry_dji.py`: 11 testów binary MP4/protobuf zamiast testów tekstowych ExifTool.
- `tests/benchmark_dji_native.py`: benchmark na podanym MP4 z 15 reprezentatywnymi próbkami.
- `tests/verify_real_telemetry.py`: zachowany opcjonalny test integracyjny.
- `src/main.py`: zachowano istniejącą fabrykę i ładowanie w tle; GUI nie zna parsera danego formatu.

Interfejs: get_at, get_datetime_at, get_overlay_text, generate_ass. DJI pokazuje CAMERA / DATE TIME / TIME / ISO / EXP. Nie parsuje GPS, IMU, WB, quaternionów ani dbgi.

## Rzeczywisty Action 6 i odczyt MP4

`D:\GoPro\DJI_20260928064217_0001_D.MP4`: **14 979 817 869 bajtów = 14,98 GB = 13,95 GiB**.

Top-level: ftyp, free, free, mdat, moov, free. mdat w offset 4080 ma 14 975 702 253 bajty i zostaje pominięty przez seek. moov w offset 14 975 706 333 ma 4 024 137 bajtów; tylko jego payload jest wczytywany do RAM.

djmd: **track ID 3, indeks 2, handler CAM meta**, timescale 30000, **62 218 próbek**. dbgi jest ignorowany. Clip metadata wskazuje **dvtm_ac206.proto** i model **DJI OsmoAction6**, normalizowany do **DJI Osmo Action 6**.

stsd wskazuje codec; stsz wskazuje rozmiary próbek; co64/stco wskazuje offset chunku; stsc wskazuje liczbę próbek w chunku. Offset próbki = offset chunku + suma rozmiarów wcześniejszych próbek w chunku. W prawdziwym pliku jest jedna próbka na chunk. Testy obejmują również zmienne liczby próbek w chunku, stco i stały rozmiar stsz.

Kod czyta `open(..., buffering=0)`, `seek(offset)`, `read(sample_size)` tylko dla djmd. Waliduje zakresy względem mdat. Nie skanuje danych wideo, audio ani debug; nie kopiuje filmu ani tracku.

Python pobrał **12 593 440 bajtów**, w tym **8 569 255 bajtów djmd** — około **0,084% MP4**. Pozostałe bajty to moov i nagłówki. Jest to liczba bajtów zwróconych do Pythona; cache/readahead systemu operacyjnego może wykonywać dodatkowe fizyczne I/O.

## Timestamp i czas rzeczywisty

DTS pochodzi z stts, PTS = DTS + ctts, jeśli występuje. ctts v0 unsigned i v1 signed są obsługiwane. elst przelicza zwykły edit o prędkości 1 i opcjonalny pusty edit na movie timeline.

Prawdziwy stts: `(1,3003), (62217,1001)`. ctts brak, elst bez przesunięcia. Pierwsze timestampy: **0.000000, 0.100100, 0.133466667 s**. Wyliczanie FrameNumber/FPS byłoby tutaj błędne. Zakres: **0.000000–2076.040633333 s**. Diagnostyczny ffprobe potwierdził timestampy, długości i offsety pierwszych sześciu pakietów. Dominujący interwał stts daje FPS 30000/1001.

get_at używa posortowanej tablicy timestampów + bisect_left, O(log N), wybierając najbliższą próbkę. FrameNumber nie jest źródłem czasu.

Start datetime: mvhd, fallback mdhd; obsługiwane wersje 0/1, epoch 1904-01-01 UTC. W tym pliku mvhd/mdhd zawierają **2026-09-28 04:42:18 UTC**, lokalnie **2026-09-28 06:42:18 +02:00**. MP4 timecode **06:42:18;17** potwierdza sekundę 18. Nazwa pliku wskazuje sekundę 17; nie użyto jej do arbitralnego przesunięcia. Nie ma niezależnego zegara do potwierdzenia faktycznej godziny; kontener i timecode są zgodne. sample.dt = start datetime + sample.timestamp. Konwersja lokalnej strefy jest taka jak w GoPro.

## Protobuf i rzeczywiste wartości

Własny parser obsługuje varint (wire 0), fixed64 (1), length-delimited (2) i fixed32 (5), bounds oraz przepełnienia. Pomija niepotrzebne payloady bez deserializacji zagnieżdżonego drzewa. Wymaga znanego schematu ac203/ac204/ac206 z clip metadata.

- Model: `1 → 1 → 10`, UTF-8; schemat: `1 → 1 → 1`.
- FrameNumber: `3 → 1 → 1`, varint.
- ISO: `3 → 2 → 3 → 1`, float little-endian/fixed32, dodatnie i skończone → int. Brak = None, bez fallback ISO=100.
- Exposure: `3 → 2 → 4 → 1`, repeated int32, packed lub unpacked. Dwa dodatnie elementy to licznik/mianownik; wynik w sekundach.

Bezpośrednie potwierdzenie z Action 6: próbka 0 `[1,145]`, próbka 165 `[1,134]`, próbka 31109 `[1,500]`, ostatnia `[1,185]`. ISO odpowiednio 6400, 6400, 3200, 6400. Brak/uszkodzenie daje None, a nakładka pomija tę linię. Zero uszkodzonych próbek w rzeczywistym pliku.

## Benchmark DJI

Ostatni samodzielny pomiar na dużym pliku:

| Etap | Czas |
| --- | ---: |
| Wykrycie tracku, odczyt nagłówków i moov | 0.006831 s |
| Odczyt/przeliczenie sample tables | 0.053391 s |
| Odczyt zakresów djmd | 0.316798 s |
| Parser protobuf | 0.753675 s |
| Całe DJITelemetry(path), pomiar zewnętrzny | **1.230553 s** |

Powtórzenia po optymalizacji: **1,22–1,30 s** samodzielnie, **1,43–1,73 s** równolegle z odtwarzaniem Qt.

**Pierwszy odczyt podczas prac trwał 10,234 s**, przed optymalizacją: I/O **7,960 s**, protobuf **1,949 s**. Wąskie gardła: rozproszone odczyty i nadmiar wywołań varint. cProfile wykazał 2,675 mln wywołań varint; dodano bezpieczną ścieżkę jednobajtowych kluczy/wartości i pomijanie nieobecnego clip header. Parser spadł do około 0,75 s. Szybsze kolejne odczyty korzystają z cache OS.

Nie czyszczono globalnego cache; po optymalizacji nie przeprowadzono kontrolowanego zimnego odczytu. **Nie gwarantujemy <2 s dla zimnego cache lub wolnego dysku**. Wtedy ograniczeniem pozostaje rozproszone I/O. GUI pozostaje responsywne dzięki odczytowi w tle.

Powtórzenie:

```powershell
python tests/benchmark_dji_native.py D:\GoPro\DJI_20260928064217_0001_D.MP4
```

Pierwsze 5, 5 ze środka i ostatnie 5 próbek (indeks od zera):

| Indeks | Timestamp s | ISO | Exposure s | Offset MP4 | Bajty |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.000000000 | 6400 | 0.006896551724 | 4096 | 277 |
| 1 | 0.100100000 | 6400 | 0.006944444444 | 365906 | 136 |
| 2 | 0.133466667 | 6400 | 0.007042253521 | 383585 | 136 |
| 3 | 0.166833333 | 6400 | 0.007092198582 | 408510 | 136 |
| 4 | 0.200200000 | 6400 | 0.007142857143 | 434388 | 136 |
| 31109 | 1038.070366667 | 3200 | 0.002000000000 | 7485252812 | 138 |
| 31110 | 1038.103733333 | 3200 | 0.002000000000 | 7485486558 | 138 |
| 31111 | 1038.137100000 | 3200 | 0.002000000000 | 7485874217 | 138 |
| 31112 | 1038.170466667 | 3200 | 0.002000000000 | 7486114712 | 138 |
| 31113 | 1038.203833333 | 3200 | 0.002000000000 | 7486357248 | 138 |
| 62213 | 2075.907166667 | 6400 | 0.005405405405 | 14974730779 | 138 |
| 62214 | 2075.940533333 | 6400 | 0.005405405405 | 14974941894 | 138 |
| 62215 | 2075.973900000 | 6400 | 0.005405405405 | 14975133322 | 138 |
| 62216 | 2076.007266667 | 6400 | 0.005405405405 | 14975329206 | 138 |
| 62217 | 2076.040633333 | 6400 | 0.005405405405 | 14975510494 | 138 |

## GoPro — regresja

`D:\GoPro\GX010338.MP4`: **12 250 451 480 bajtów = 12,25 GB = 11,41 GiB**. Kamera **MISSION 1**, **63 960 próbek**.

Bezpośredni GPMFTelemetry: **1,864893 s**. Nowa fabryka + GPMFTelemetry: **1,621120 s**, przy cache OS. Nie należy interpretować tej różnicy jako przyspieszenia parsera.

Porównano wszystkie 63 960 próbek (timestamp, ISO, exposure, datetime), nakładki w 0 / 1 / 5,57 / 60 / 300 s i końcu telemetrii oraz dwusekundowy ASS. **Wszystko identyczne**. Parser ekstrakcji GPMF, audio sync, master/slave, skalowanie i kodowanie nie zmieniły się. Wyszukiwanie najbliższej próbki w GoPro używa teraz bisect.

Najważniejsza optymalizacja eksportu ASS: wcześniejsze `get_at()` przeglądało liniowo 63 960 próbek dla każdej klatki. Nowa, posortowana tablica timestampów i bisect robią to w O(log N). Cały ASS dla 35:35.15, 63 990 wydarzeń i 8 162 730 bajtów wygenerował się w **0,398 s** na tym komputerze. Podgląd próbuje telemetrię rzadziej, dlatego nie ujawniał tego kosztu. Sprawdzono zgodność wyszukiwarki z poprzednim liniowym wynikiem, w tym identyczny ASS z przykładowego krótkiego odcinka.

GoPro 5,570 s: MISSION 1 / 2026-10-02 07:39:45 / TIME : 5.570s / ISO : 1254 / EXP : 1/50.

## Testy, podgląd i eksport

- unittest: **11/11 PASS**, compileall src/tests: PASS.
- Testy: rzeczywista pierwsza próbka Action 6, packed/unpacked int32, ISO float, brak/uszkodzenie, wire 0/1/2/5, unknown payloads, bounds, stco/co64, zmienny stsc, stały stsz, clock v0/v1, podpisane ctts, edit list, native factory bez subprocess, Null dla dbgi, nearest, daty, zgodność overlay/ASS, anulowanie.
- Schematy ac203/ac204/ac206: testy syntetyczne. Fizycznie zweryfikowano Action 6: duży plik oraz wcześniejszy 13,89-MB z F:\DJI (74 próbki).
- Qt offscreen: rzeczywiste odtwarzanie obu dużych plików i automatyczna aktualizacja pięciu linii przez timer main.py — PASS.
- Podczas odczytu działał równoległy timer GUI; sprawdzono ponowne włączenie eksportu, zastąpienie pliku i anulowanie starego wyniku — PASS.
- FFmpeg wyrenderował klatkę z native ASS; obraz sprawdzono wizualnie. Zapisano także krótki eksport H.264 960x540 z tym samym ASS. Nie wykonano pełnego 34-minutowego eksportu porównawczego ani testów wszystkich GPU encoderów.

## Limit rozdzielczości i możliwości encodera

Maksymalny rozmiar planszy wyjściowej to 3840×2160 (4K UHD). Po ułożeniu klipów obok siebie lub jeden nad drugim filtr skaluje całą planszę równomiernie, ograniczając ją do 4K i zachowując proporcje. Wybrana skala x1/x0.5/x0.25 nadal obowiązuje; output nie jest powiększany ponad rozdzielczość wejścia.

Przed przygotowaniem ASS program uruchamia dla wybranego sprzętowego encodera jednoklatkową próbę FFmpeg z syntetyczną planszą, kończącą się do null muxera. Nie czyta materiału źródłowego ani nie zapisuje filmu. Sprawdza 4K, potem 1080p i 720p. Filtr eksportu używa najwyższego poziomu obsługiwanego przez wybraną kombinację encoder/codec. Gdy urządzenie nie obsługuje nawet 720p albo sesja GPU jest niedostępna, ten eksport przechodzi na software encoder tego samego kodeka.

Rzeczywisty komputer: ekran 3840×2160, próba AMD AMF H.264 i H.265 w 4K przechodzi; QSV H.264/H.265 nie może utworzyć sesji MFX (`-9`). Używany FFmpeg to build z 2023-06. Nie ma filtrów `scale_d3d11` ani `overlay_d3d11`, wymaganych dla kompozycji bez pobierania klatek do pamięci CPU. Oficjalna lista FFmpeg obejmuje filtr `scale_d3d11` dodany później, lecz aktualna instalacja go nie ma; samo skalowanie nadal nie rozwiązuje GPU łączenia i tekstu ASS. Próba dekodowania HEVC przez Vulkan zgłasza brak `VK_KHR_video_decode_queue` dla zintegrowanego AMD. Aplikacja blokuje eksport, jeśli musiałby korzystać z CPU filtrów; nie przełącza na encoder CPU. Pełny eksport GPU wymaga nowego kompozytora GPU obsługującego łączenie dwóch klipów i renderer napisów. Sama próba AMF sprawdza tylko encoder, nie kompletną ścieżkę.

Podgląd: `dji-native-overlay.png`; krótki eksport: `dji-native-export.mp4`.

## Usunięte elementy ExifTool i pakowanie

Z kodu DJI usunięto resolver, wersjonowanie, proces, timeout procesu, parser tekstowy, format pól, komunikaty o braku ExifTool, WB i extra_samples. Usunięto poprzedni raport ExifTool.

`tools/exiftool` nie istnieje w projekcie. Katalog zewnętrznego narzędzia został odłożony poza repo; aplikacja go nie używa. Runtime DJI nie wymaga Perla ani zewnętrznego dekodera.

Istniejące nazwy `to_exiftool_json` w module GoPro oznaczają własny eksport JSON, nie uruchamianie programu; pozostawiono je bez zmian. Do EXE należy dołączyć nowe moduły Python i dotychczasowe zależności programu, bez tools/exiftool / Perl / exiftool_files.

## Ograniczenia i dokumentacja

Obsługiwane są klasyczne MP4 z moov/stbl. Fragmented MP4 (moof), złożone wielosegmentowe edit lists, rate !=1, stz2 i zmiana sample description nie są obsługiwane; nie występują w podanych plikach. Limity: moov 64 MiB, próbka 1 MiB, 10 mln próbek. Action 2/3 i nieznane schematy nie mają gwarantowanej obsługi. Brak prawdziwych Action 4/5 do weryfikacji integracyjnej.

Parser napisano samodzielnie, korzystając z dokumentacji pól. Nie skopiowano implementacji referencyjnej. telemetry-parser ma MIT OR Apache-2.0.

- https://github.com/AdrianEddy/telemetry-parser/blob/master/src/dji/mod.rs
- https://github.com/AdrianEddy/telemetry-parser/blob/master/src/dji/dvtm_library.proto
- https://github.com/AdrianEddy/telemetry-parser/blob/master/src/dji/dvtm_wm169.proto
- https://github.com/AdrianEddy/telemetry-parser/blob/master/src/dji/dvtm_oq101.proto
- https://github.com/AdrianEddy/telemetry-parser/blob/master/src/dji/dvtm_eagle4_wa530.proto
- https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/DJI.pm — wyłącznie dokumentacja ścieżek, bez uruchamiania ExifTool.
