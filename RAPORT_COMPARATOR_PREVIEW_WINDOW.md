# Comparator – raport końcowy podglądu eksportu

## Zmiany

- Usunięto integrację ntfy z aplikacji, jej konfigurację, test wysyłki i moduł implementacji. Powiadomienia o wyniku eksportu pozostają lokalne w GUI.
- Podgląd wypełnia cały widget. Ustawienie domyślne to **Rozciągnij**; dostępne są też **Dopasuj** (zachowuje cały kadr) i **Wypełnij kadrem** (centralne przycięcie). Zmiana trybu działa od razu, bez restartu FFmpeg.
- Próbka jest dobierana dynamicznie do obszaru podglądu, z zachowaniem proporcji, parzystych wymiarów, limitu 1600×900 i bez powiększania ponad kompozycję źródłową. Po zmianie rozmiaru okna istniejąca klatka dopasowuje się po stronie GUI; FFmpeg nie jest restartowany.
- W grafie FFmpeg strumień zostaje rozdzielony po złożeniu i ustawieniu czasu/FPS. Gałąź eksportu zachowuje dotychczasowe dopełnienie MP4, a podgląd jest pobierany z kompozycji przed dopełnieniem, więc nie pokazuje czarnych pasów eksportowych. Podgląd nadal używa jednej instancji FFmpeg, TCP, 5 FPS i ograniczonej kolejki; nie dodano dekodowania.

## Pomiar RTX 5070 Ti

Wykonano `python work/benchmark_preview_dynamic.py` na materiałach testowych. Każdy wariant miał osobny warm-up 300 klatek, a następnie dwa pomiary po 3000 klatek; warm-up nie wchodzi do FPS z pomiarów. Eksport testowy: HEVC NVENC p4, 3840×2160. Próbka podglądu: 1568×882 przy 5 FPS.

| Wariant | FPS, przebieg 1 | FPS, przebieg 2 | Średnia | Czas, średnio | Peak RSS, średnio |
|---|---:|---:|---:|---:|---:|
| Bez podglądu | 134,73 | 135,07 | 134,90 | 22,24 s | 1921,92 MB |
| Podgląd dynamiczny 1568×882 | 133,36 | 133,15 | 133,26 | 22,51 s | 2116,43 MB |

Wpływ na FPS wyniósł około **−1,22%**, poniżej ustalonego limitu 3%. FFmpeg wysłał po 500 JPEG-ów na przebieg pomiarowy; GUI wyświetliło po 107 i odrzuciło po 393 jako starsze klatki. Średnia wielkość JPEG wyniosła około 21,7 kB. Podgląd nie wstrzymał enkodera.

Wynik dotyczy tego konkretnego RTX 5070 Ti, wejść, kompozycji i przebiegu testowego; nie jest gwarancją dla innych nagrań ani konfiguracji.

## Weryfikacja

- `python -m pytest -q` — **210 passed, 2 skipped**.
- Testy Qt obejmują tryby skalowania, wypełnianie widgetu, zmianę trybu bez restartu TCP, ustawienie domyślne i migrację starej konfiguracji.
- Test grafu podglądu pokrywa 2160p i Podwójne 4K, układy lewo/prawo i góra/dół, prędkości 1×/2×/4× oraz dopełnianie włączone i wyłączone.
- Aplikacja źródłowa uruchomiła się jako „Comparator”. Warstwa CUA nie udostępniła okien (pusta lista aplikacji), więc nie udało się zachować zrzutu ekranu ani wykonać inspekcji AX. Stan widgetów i zachowanie opcji zweryfikowano automatycznie testami Qt.
- Nie zmieniano ASS, audio, orientacji ani logiki NVENC poza rozdzieleniem gałęzi obrazu potrzebnym do wyświetlenia podglądu przed dopełnieniem.

- Po zakończeniu testów wysłano status na wskazany temat ntfy; endpoint potwierdził przyjęcie HTTP 200.
