# Raport: wybór rozdzielczości porównania

Data: 2026-10-08. Projekt Comparator.

## Zmiany

- `src/options_dialog.py` – w istniejącym oknie „Opcje”, w sekcji Comparator, dodano grupę „Rozdzielczość porównania”, radio Full HD i 4K UHD, informację o końcowym rozmiarze kompozytu oraz zachowanie Checkboxa dopełniania.
- `src/main.py` – ustawienie jest zsynchronizowane z istniejącą kontrolką skali. Element trybu 4K ma `itemData="dual4k"` i widoczną etykietę „4K UHD”; eksport nadal wysyła istniejący `dual_4k=True`. Zmiana GPU/backendu lub negatywny probe przy aktywnym UHD ustawia Full HD, aktualizuje ustawienie i pokazuje przyczynę.
- `src/i18n.py` – nowe etykiety i komunikaty dla polskiego, angielskiego, niemieckiego i francuskiego.
- `src/export_prepare.py` i `src/nvidia_modern.py` – zaktualizowano wyłącznie teksty błędów, aby w UI nazwa trybu brzmiała „4K UHD na kamerę”. Logika eksportu i builder poleceń pozostały bez zmian.
- `tests/test_comparison_resolution_options.py` – testy trybów, wymiarów, dostępności, synchronizacji, ustawień, OK/Anuluj, dopełniania i bezpiecznego powrotu.
- `tests/test_nvidia_modern_pipeline.py` – dopasowano oczekiwany tekst błędu.

## Zachowanie UI i rozmiary

Full HD oznacza 1920×1080 na każdą kamerę, a nie rozmiar całego kompozytu. Końcowe wymiary wynoszą 1920×2160 dla góra/dół i 3840×1080 dla lewo/prawo. Przy zaznaczonym „Dopełniaj obraz do 4K czarnymi pasami” płótno Full HD może mieć 3840×2160.

4K UHD oznacza 3840×2160 na każdą kamerę. Końcowy kompozyt to 3840×4320 dla góra/dół i 7680×2160 dla lewo/prawo. W tym trybie Checkbox dopełniania jest nieaktywny, a jego zaznaczenie pozostaje zapamiętane; po powrocie do Full HD ponownie się uaktywnia.

Dotychczasowe x1/x0.5/x0.25 zachowują swoje znaczenie. Jeśli w głównym oknie wybrana jest skala standardowa, otwarcie Opcji pokazuje Full HD i nie zmienia skali. Wybranie UHD synchronizuje istniejący wpis `dual4k`; powrót do Full HD z dual4k ustawia x1, a przy skali standardowej pozostawia x0.5/x0.25 bez zmian.

## Konfiguracja i dostępność

Trwały wybór zapisuje się w istniejącym QSettings (`Comparator/Comparator`) pod kluczem `comparison_resolution`: `full_hd` albo `4k_uhd`. Brak klucza w konfiguracji starszej wersji oznacza Full HD. Radio aktualizuje zapis dopiero po OK; Anuluj nie zapisuje rozdzielczości ani Checkboxa. `options_data` i kontrolka głównego okna odzwierciedlają tę samą wartość.

Radio UHD pozostaje widoczne, ale jest nieaktywne, dopóki nie są spełnione wszystkie warunki: wybrany NVIDIA i backend AUTO, pozytywny istniejący probe NVIDIA Modern, pozytywny probe HEVC NVENC dla docelowego rozmiaru z `split_encode_mode forced` oraz oba wejścia mają 3840×2160. Wymiary dwóch plików są sprawdzane FFprobe w wątku roboczym. Probe Modern/NVENC korzysta z istniejącego cache; otwarcie Opcji nie uruchamia probe’ów ani benchmarku i nie blokuje GUI.

Pozytywny probe na rzeczywistej RTX 5070 Ti (compute capability 12.0) z plikami `K:\GoPro\2026-10-06\GX010345.MP4` i `K:\GoPro\2026-10-06\DJI_20261006062240_0005_D.MP4` potwierdził NVIDIA Modern, oba materiały 3840×2160 i split encode dla wybranego układu; Radio UHD zostało aktywowane. Test symulujący Quadro P400 / Pascal / CC 6.1 potwierdza klasę Legacy i nieaktywną opcję UHD. Symulacja P400 nie jest testem fizycznej karty.

Jeśli zapisane UHD nie przejdzie dostępności po wczytaniu materiałów albo zmianie karty/backendu/presetu/układu, aplikacja wraca do Full HD, aktualizuje QSettings i informuje użytkownika. Warunki eksportu są również sprawdzane przez istniejące `export_prepare`; UI nie może wymusić nieobsługiwanego UHD.

## Weryfikacja wizualna i testy

Podgląd okna Opcje z Qt offscreen miał 533×449 px. Dolna krawędź przycisków OK/Anuluj znajdowała się na y=432, więc przyciski mieszczą się w oknie. Elementy i etykiety są dodatkowo asercjami testów. Środowisko offscreen nie udostępnia rodzin fontów Qt, przez co zapisany PNG zastępował znaki placeholderami; nie wpływało to na geometrię ani testy tekstu.

Pełne `pytest -q --tb=short`: 110 passed, 2 skipped, 2 failed. Oba błędy dotyczą istniejących testów eksportu wymagających nieobecnego `tests/artifacts/tone440.mp4`. Zestaw opcji rozdzielczości, GUI, NVIDIA Modern i backendów: 73 passed, 1 skipped. `compileall` dla `src` i `tests` zakończył się poprawnie.

Zmiana nie przebudowuje pipeline’u FFmpeg, CUDA/NVDEC/scale_cuda/hwdownload, NVENC presetów, split encode, ASS, audio ani synchronizacji.
