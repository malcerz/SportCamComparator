# Comparator — raport końcowy podglądu eksportu

Data: 8 października 2026 r. Testy wykonano na NVIDIA GeForce RTX 5070 Ti.

## Zmiany

Podgląd dobiera teraz największe parzyste wymiary mieszczące się jednocześnie w obszarze obrazu, źródle i limicie 1600×900. Zachowuje proporcje kompozytu, nie powiększa źródła, a zmiana rozmiaru okna skaluje bieżącą klatkę bez restartowania FFmpeg. Dla pola 1973×882 kompozytu 16:9 próbka wynosi 1568×882. Testy obejmują także Dual 4K z dopełnieniem i bez niego.

Próbkowanie pozostało na 5 fps materiału. Przy eksporcie około 4,5× realtime daje to ok. 22 próbki/s zegarową, z których GUI wyświetla około 5/s. Sterowanie częstością próbek w trakcie działania wymagałoby dodatkowej komunikacji i zmiany grafu FFmpeg; zmierzony koszt obecnego podglądu 1568×882 to ok. 0,60% przepustowości, więc pozostawiono prosty wariant bez zmian w architekturze.

## Pomiar przepustowości

Każdy profil używał tego samego grafu produkcyjnego z dwoma rzeczywistymi klipami, ASS, NVDEC/CUDA i HEVC NVENC p4, 3840×2160, 10 Mbit/s. Dla każdego wykonano 300 klatek rozgrzewki i dwa przebiegi pomiarowe po 3000 klatek do NUL.

| Profil | FPS przebiegów | Średnia | Różnica do braku podglądu |
|---|---:|---:|---:|
| Bez podglądu | 133,84 / 134,32 | 134,08 | — |
| Podgląd 1280×720 | 134,20 / 133,64 | 133,92 | −0,12% |
| Podgląd 1568×882 | 133,35 / 133,21 | 133,28 | −0,60% |

Przy 1568×882 FFmpeg dostarczył po 500 JPEG-ów na przebieg; GUI wyświetliło 107, zastąpiło 393 starsze próbki i odrzuciło 0. Średni JPEG miał 28,6 KB, a średnie opóźnienie odbiór→GUI wyniosło 24 ms. Peak RSS: 2236–2237 MiB. Wyniki są zgodne z ręcznym zakresem wydajności; większa próbka zwiększyła rozmiar JPEG względem 1280×720, przy spadku FPS poniżej 1%.

Polecenia odtwarzające pomiary:

```powershell
python work\benchmark_preview_1280_reference.py
python work\benchmark_preview_dynamic.py
```

## Zatrzymanie i rozłączenie TCP

Test wstrzymał odbiór JPEG-ów na 6 s przy małym buforze TCP, po czym rozłączył odbiornik podczas eksportu. W tym czasie główny HEVC przeszedł z klatki 123 do 907 (784 klatki). MP4 został sfinalizowany z HEVC 3840×2160 i wszystkimi 3000 klatkami w 22,69 s. Rozłączenie zgłosiło błąd wyłącznie wyjścia FIFO/TCP: FFmpeg zakończył się kodem Windows 4294957242 (socket reset -10054), mimo kompletnego głównego pliku. Test potwierdza, że kodowanie HEVC kontynuowało pracę bez czekania na odbiornik; awaria dodatkowego wyjścia podglądu nadal jest widoczna jako niezerowy status procesu.

```powershell
python work\test_preview_tcp_disconnect.py
```

## Walidacja

- `python -m pytest -q`: **177 passed, 2 skipped**.
- `python -m compileall -q src tests work/benchmark_preview_1280_reference.py work/benchmark_preview_dynamic.py work/test_preview_tcp_disconnect.py`: zaliczone.
- Szczegółowe dane pomiarów: `work/ass-benchmark/preview-1280-reference-results.json`, `work/ass-benchmark/preview-dynamic-results.json` i `work/ass-benchmark/preview-tcp-disconnect-results.json`.
