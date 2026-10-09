# Podgląd finalnych klatek podczas eksportu D3D11

## Implementacja

Podgląd jest osobną gałęzią `ExportPreview`, uruchamianą po udanym `GpuCompositor::Composite`, przed `HwEncoder::SendFrame`. Jedyne źródło obrazu to `compositor.GetOutputTexture()`: ta sama finalna tekstura NV12 z dwoma wejściami, rotacją, dopasowaniem obrazów, czarnymi pasami i obiema telemetriami, którą otrzymuje encoder. Podgląd nie dekoduje ponownie wejść i nie przechwytuje okna ani pulpitu.

Wymiary są odczytywane przez `ID3D11Texture2D::GetDesc`, a nie wyliczane z wymiarów wejść. Współczynnik `min(1, 960/sourceWidth, 540/sourceHeight)` dopasowuje cały canvas do 960×540. Oddzielny D3D11 VideoProcessor skaluje i konwertuje NV12/P010 do BGRA. Produkcyjny compositor obecnie zwraca NV12, również dla źródeł GoPro/DJI HEVC Main10/P010. Podgląd nie zmienia formatu encodera. Nie występuje CPU resize dużej klatki, sws_scale ani programowy AVFrame w ścieżce eksportu.

Harmonogram używa PTS finalnej osi czasu: `pts >= nextPts`, następnie `nextPts += 1.0`. To jedna próbka na sekundę filmu; przy szybszym eksporcie próbki mogą napływać częściej niż raz na sekundę zegarową. GUI pokazuje najnowszą miniaturę maksymalnie raz na sekundę zegarową, z wyjątkiem natychmiastowej pierwszej klatki.

## Odczyt GPU i brak oczekiwania renderera

Pierścień zawiera trzy staging textures BGRA, każdą maksymalnie 960×540, oraz query EVENT, timestamp początku/końca i DISJOINT. Włączenie podglądu nie tworzy pełnowymiarowej staging texture. Rozmiar małej tekstury jest sprawdzany asercją, a odbiornik GUI dodatkowo odrzuca większe deklarowane wymiary.

Kolejność dla próbki: Begin DISJOINT → timestamp → VideoProcessorBlt → CopyResource małego BGRA do wolnego staging slotu → timestamp → End DISJOINT → End EVENT. Przy kolejnych klatkach renderer odpytuje wcześniejsze sloty przez `GetData(..., D3D11_ASYNC_GETDATA_DONOTFLUSH)`. S_FALSE pozostawia slot pending. Dopiero S_OK i zakończone EVENT pozwalają na `Map(READ, DO_NOT_WAIT)`; WAS_STILL_DRAWING odkłada odczyt. Kopiowane są tylko małe wiersze z uwzględnieniem RowPitch, po czym następuje Unmap.

Nie ma renderowego Sleep, Flush, oczekiwania query, blokującego Map ani join wątku JPEG. Zajęte trzy sloty powodują odrzucenie próbki. Kolejka CPU ma maksymalnie dwie miniatury; nowsza zastępuje najstarszą. Przekazanie do kolejki używa try_lock: zajęty mutex oznacza drop, nie oczekiwanie. Pamięć JPEG i IPC należy wyłącznie do wątku CPU; nie korzysta on z urządzenia ani kontekstu D3D11.

`PREVIEW_AVG_GPU_MS` mierzy rzeczywiste znaczniki GPU obejmujące skalowanie/konwersję i copy, wyłącznie dla gotowych, niedysjunktywnych próbek. `PREVIEW_AVG_CPU_MS` mierzy konwersję małego BGRA do BGR, JPEG WIC i przygotowanie pakietu, bez oczekiwania IPC.

## JPEG, IPC i GUI

JPEG powstaje przez Windows Imaging Component, jakość 80%. Zależności systemowe: windowscodecs i ole32. Nie dodano ciężkiej biblioteki kodowania. Wątek renderujący nie koduje JPEG ani base64.

Zastosowano osobny lokalny named pipe, obsługiwany przez QLocalServer/QLocalSocket. Jest to świadomy wybór względem proponowanego rozszerzenia stdout: QProcess ma zwykły pipe stdout, a blokujący zapis obrazu pod współdzielonym mutexem mógłby zatrzymać zapis postępu w rendererze. Oddzielny kanał zachowuje istniejący stdout JSONL postępu bez przeplatania danych i bez włączania dużych obrazów do logów.

Pakiet ma jednoznaczny framing: dwa uint32 little-endian (`metadata_length`, `jpeg_length`), JSON UTF-8 z type/pts/frame/width/height/encoding, następnie dokładnie jpeg_length bajtów JPEG. Surowe JPEG nie są mieszane ze stdout. Nazwa kanału to losowy ASCII UUID przekazany w configu. Brak konsumenta przy eksporcie CLI bez preview_pipe nie uruchamia gałęzi miniatur.

Zapis IPC jest overlapped, wykonywany wyłącznie przez worker. Worker ma limit 20 ms na zapis. Rozłączenie lub backpressure wyłącza podgląd; częściowo wysłanego pakietu nie można bezpiecznie pominąć w strumieniu bajtów, dlatego kanał zostaje zamknięty. Anulowanie sygnalizuje event i stop, bez oczekiwania na JPEG. Worker zachowuje własną pamięć do zakończenia anulowania operacji overlapped; to oczekiwanie nie odbywa się w rendererze.

GUI zawiera domyślnie zaznaczony „Podgląd eksportu”. Okno pokazuje miniaturę finalnego canvasu, aktualny postęp, klatkę, FPS i ETA oraz przycisk anulowania. Wielkość okna jest ograniczana do dostępnego ekranu, obraz zachowuje proporcje. Odbiornik składa fragmentowane pakiety, ogranicza ich rozmiar, utrzymuje tylko najnowszą oczekującą miniaturę i wyświetla obraz nie większy niż 960×540. Zamknięcie samego okna podglądu nie anuluje MP4. Legacy nie uruchamia okna miniatur. Qt Quick player, preview_sync i dostawcy telemetrii nie zostały zmienione przez tę poprawkę.

Awaria gałęzi podglądu emituje warning `PREVIEW_DISABLED_AFTER_ERROR: <reason>` i wyłącza tylko tę gałąź. Błędy głównego kompozytora, dekodera, encodera i muxera nadal są błędami eksportu.

## Weryfikacja

Wyniki końcowe i pomiary zostaną uzupełnione po zakończeniu trwających testów. Raport na tym etapie nie stanowi potwierdzenia akceptacji.
