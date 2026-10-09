# Comparator — izolacja awarii podglądu TCP

## Wynik

Awaria dodatkowego strumienia MJPEG nie przerywa już eksportu widzianego przez GUI jako niepowodzenie, jeśli FFmpeg zakończył główne kodowanie, a zapisany MP4 przejdzie pełną walidację. Używany FFmpeg przy rozłączeniu TCP nadal potrafi zakończyć proces kodem odpowiadającym `-10054`; test `tee` z `onfail=ignore` był dostępny, ale obniżył FPS o ok. 14%, więc został odrzucony. Zachowana została dotychczasowa ścieżka jednego dekodowania i głównego HEVC NVENC oraz pomocniczego FIFO/TCP.

## Klasyfikacja i walidacja

Kod odzyskuje wyłącznie niezerowy wynik z jednoznacznym błędem `out#1/fifo`/`vost#1`, postępem `progress=end` i końcową liczbą klatek większą od zera. Anulowanie, błąd kodera HEVC oraz błąd głównego `out#0` pozostają błędami eksportu. Przy kandydacie na awarię preview GUI wyłącza i zamyka odbiornik TCP, opuszcza ekran podglądu i asynchronicznie waliduje MP4 przez FFprobe. Sukces wymaga strumienia HEVC, właściwego wymiaru, poprawnego kontenera i czasu trwania w tolerancji 0,5 s / 0,5%; gdy FFprobe podaje `nb_frames`, wymagana jest też zgodność liczby klatek (±2). Przy błędzie walidacji nadal wysyłane jest powiadomienie o błędzie.

Powiadomienie końcowe jest wysyłane najwyżej raz. Zweryfikowany eksport po awarii TCP trafia do ścieżki sukcesu ntfy, a rzeczywisty błąd główny do ścieżki błędu. Testy timeoutu/HTTP ntfy są nieblokujące i nie zmieniają wyniku eksportu.

## Wyniki prób A–I

- **A — aktywny podgląd:** próba zastojowa zaczęła się z aktywnym odbiornikiem; FFmpeg zakończył się kodem 0, MP4 HEVC 3840×2160, 3000 klatek.
- **B — podgląd wyłączony:** eksport HEVC do MP4 zakończony kodem 0; FFprobe potwierdził 3840×2160, 100,100 s i 3000 klatek.
- **C — odbiornik nie czyta przez 6 s:** postęp głównego wyjścia wzrósł o 785 klatek; proces zakończył się kodem 0, plik ma 3000 klatek.
- **D — zerwanie TCP:** FFmpeg zwrócił `4294957242` (Windowsowa reprezentacja kodu resetu połączenia); ślad wskazał wyłącznie FIFO preview. FFprobe potwierdził HEVC 3840×2160, 3000 klatek i poprawny czas. Eksport w aplikacji jest uznany za sukces dopiero po tej walidacji.
- **E — zamknięcie odbiornika:** taki sam sklasyfikowany błąd FIFO; główne wyjście dokończyło 3000 klatek, MP4 przeszło FFprobe.
- **F — anulowanie:** test uruchamia rzeczywisty QProcess oczekujący na wejście, anuluje go przez ścieżkę GUI, sprawdza zakończenie procesu, powrót do zwykłego odtwarzacza oraz dokładnie jedno powiadomienie.
- **G — rzeczywisty błąd kodera:** FFmpeg z `hevc_nvenc` i nieprawidłowym presetem zakończył się niezerowo błędem ustawień enkodera; nie kwalifikuje się jako awaria preview.
- **H — rzeczywisty błąd zapisu MP4:** FFmpeg z `hevc_nvenc` próbował zapisać plik do nieistniejącego katalogu; otrzymał błąd otwarcia głównego `out#0/mp4`, nie kwalifikuje się jako awaria preview.
- **I — błąd/timeout ntfy:** istniejący test wymusza HTTP 503 i timeout oraz potwierdza nieblokującą obsługę.

Testy `stall`, `disconnect` i `close` zamykają odbiornik w `finally`; test cyklu życia preview sprawdza zamknięcie serwera. Test anulowania sprawdza, że QProcess nie pozostaje aktywny. Testy powiadomień obejmują pojedyncze powiadomienie końcowe.

## Pomiar wydajności RTX 5070 Ti

Benchmark wykonano dla dynamicznego preview **1568×882, 5 FPS**, wyjścia 3840×2160 HEVC NVENC p4. Każdy wariant dostał osobny przebieg warm-up 300 klatek, nieuwzględniony w FPS, a następnie dwa przebiegi po 3000 klatek.

| Wariant | Przebiegi mierzone | Średni FPS | Średnia szybkość FFmpeg | Szczyt RSS |
|---|---:|---:|---:|---:|
| Bez podglądu | 135,00 / 134,51 | **134,76** | 4,57× / 4,56× | 1,88 GiB |
| Podgląd 1568×882 | 131,99 / 133,37 | **132,68** | 4,48× / 4,52× | 2,19 GiB |

Zmierzony narzut wyniósł **1,54%** względem przebiegu bez podglądu. W przebiegu preview odebrano 500 JPEG-ów; GUI wyświetliło 109, a tryb latest-only odrzucił/przykrył 391 starszych próbek. Rozdzielczość 1568×882 i 5 FPS nie zostały zmienione.

Polecenia odtwarzające benchmark i próby TCP:

```powershell
cd K:\GoPro\Comparator
python work\benchmark_preview_dynamic.py
python work\test_preview_tcp_disconnect.py stall
python work\test_preview_tcp_disconnect.py disconnect
python work\test_preview_tcp_disconnect.py close
python -m pytest -q
```

## Zmienione pliki

- `src/main.py` — klasyfikacja wtórnego błędu i asynchroniczna walidacja MP4 przed sukcesem.
- `src/nvidia_modern.py` — jawna kolejność: główny plik przed dodatkowym wyjściem TCP.
- `src/export_result.py` — ścisły klasyfikator i walidator FFprobe.
- `src/export_live_preview.py` — bezpieczne zamknięcie socketu po awarii podglądu.
- `tests/test_export_result.py` — testy klasyfikacji i walidacji.
- `tests/test_export_preview.py` — integracja odzyskiwania błędu oraz anulowanie żywego procesu.
- `work/test_preview_tcp_disconnect.py` — próby zastojów, zerwania i zamknięcia odbiornika.
- `work/benchmark_comparator_features.py` — obsługa zapisu pełnego pliku w wariancie bez podglądu dla prób.

## Walidacja

`python -m pytest -q` — **186 passed, 2 skipped**.
Benchmark RTX 5070 Ti i trzy próby TCP wykonano na rzeczywistej karcie i plikach z `K:\GoPro\2026-10-06\`.


