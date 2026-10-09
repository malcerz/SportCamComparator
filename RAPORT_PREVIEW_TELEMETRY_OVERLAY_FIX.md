# Naprawa telemetrii podglądu

Data: 2026-10-06. Windows, PySide6/Qt 6.11.1, AMD Radeon Graphics.
Zakres: PlayerWidget preview, dwie etykiety diagnostyczne w konstruktorze MainWindow, testy i raport. Nie zmieniano parserów telemetrii, preview_sync.py ani żadnego źródła native/KomparatorGpuExporter. Nie przebudowywano native exportera.

## Dane czy rendering

MainWindow._tick nadal wywołuje get_overlay_text(position/1000) oraz set_overlay dla obu stron przy włączonej „Nakładce”. Rzeczywiste pliki:

- GoPro: D:/GoPro/GX010338.MP4, MISSION 1, 63 960 próbek.
- DJI: D:/GoPro/DJI_20261002062647_0003_D.MP4, DJI Osmo Action 6, 64 091 próbek.

Diagnostyka KOMPARATOR_DEBUG_OVERLAY=1 loguje maksymalnie raz/s na player: repr(text), widoczność, geometrię, parent, stan native i renderer. Przed naprawą oba QLabel miały poprawne CAMERA/DATE/TIME/ISO/EXP oraz isVisible=True. Zrzut prawdziwego ekranu Windows nie zawierał żadnej telemetrii. To błąd kompozycji, nie danych. Zapisano logi baseline.log i obraz baseline_window.png; parserów nie zmieniano.

Źródło Qt 6.11.1 [QVideoWidget](https://github.com/qt/qtmultimedia/blob/v6.11.1/src/multimediawidgets/qvideowidget.cpp) tworzy QVideoWindow i osadza je przez QWidget.createWindowContainer. Sam flag WA_NativeWindow=False na zewnętrznym QVideoWidget nie oznacza braku natywnej wewnętrznej powierzchni. Window container nie daje tej samej kompozycji z-order co zwykłe malowane QWidget.

## Sprawdzone warianty i finalna implementacja

1. Przed zmianą: QLabel child bezpośrednio QVideoWidget. Poprawny tekst, niewidoczny na ekranie.
2. QWidget video_container -> QVideoWidget i QLabel jako siblings; show/raise; półprzezroczystość i przepuszczanie myszy. Nadal niewidoczny. Dowód: sibling_window.png.
3. Native QLabel sibling: WA_NativeWindow=True, winId/show/raise. Nadal niewidoczny, także po wymuszeniu czerwonego, nieprzezroczystego tła. Dowody: native_sibling_window.png, native_red_window.png oraz logi ze stanem native=True. Nie uznano tego za naprawę.
4. Zastosowano przewidziany w zadaniu fallback: QQuickWidget z VideoOutput i Rectangle/Text w **tej samej scenie GPU**. Finalny parent overlay to root QQuickItem sceny preview, nie QVideoWidget i nie dodatkowe top-level window. Rectangle ma stałe z=1 nad VideoOutput. Brak QGraphicsVideoItem, brak oddzielnego native overlay, brak top-level frameless window.

[Dokumentacja QQuickWidget](https://doc.qt.io/qt-6/qquickwidget.html) opisuje jego kompozycję i brak ograniczeń native-window stacking; [VideoOutput](https://doc.qt.io/qt-6/qml-qtmultimedia-videooutput.html) udostępnia videoSink oraz contentRect. Istniejący QMediaPlayer/AudioOutput pozostają: tylko videoSink trafia do nowego render targetu. Bez mapowania/dekodowania klatek w Pythonie.

WA_NativeWindow było sprawdzone, ale nie wystarczyło. W finalnym rozwiązaniu **nie jest używane**. Qt Quick było konieczne po faktycznie nieudanych testach zwykłego i native sibling na tym Windows.

## Pozycja, wygląd i koszt aktualizacji

VideoOutput.PreserveAspectFit wylicza contentRect uwzględniający materiał, aspekt, rotację, letterbox/pillarbox i resize. Overlay x/y = contentRect.x/y + margin. Font Consolas, biały tekst, czarne tło alpha=120/255, radius=4. Margin/padding/font zależą tylko od rzeczywistej szerokości obrazu. Brak MouseArea/pointer handler; acceptedMouseButtons=NoButton.

Dla kontenera 1240×330 i obrazu 16:9: videoRect około x=326.667, y=0, width=586.667, height=330. Test potwierdza pozycję overlay wewnątrz obrazu, poza czarnymi pasami.

set_overlay porównuje tekst i ustawia wyłącznie property overlayText w scenie. Nie ustawia geometrii video, fontu, stylesheet ani nie wywołuje pełnego layoutu. QML Text/Rectangle reagują na tekst, VideoOutput nie zmienia contentRect. layout_update_count liczy realne zmiany contentRect. overlay_text_update_count liczy zmienione teksty. overlay_raise_count=0: stałe z=1 zastępuje dynamiczne raise.

## Testy Windows i screenshots

Automatyczny tests/verify_preview_overlay_windows.py uruchamia MainWindow z realnymi providerami i dwoma dużymi plikami. Sprawdza na prawdziwym ekranie Windows tekst oraz piksele, nie tylko isVisible. W trakcie QA wyłącznie główne okno testowe ma WindowStaysOnTopHint, aby inne aplikacje nie zasłoniły zrzutów. Produkt nie dostał tego flagu ani dodatkowego floating window.

Punkty GoPro i DJI: T=0, 5.570, 60 s. GoPro w T=5.570: MISSION 1, 2026-10-02 07:39:45, TIME 5.570s, ISO 1254, EXP 1/50. Tekst obu stron porównywany z właściwym providerem. Każdy obraz ma widoczne CAMERA/DATE/TIME/ISO/EXP. Sprawdzone układy LR/TB, resize, maximized i fullscreen. Czerwone tło diagnostyczne overlay także sprawdzone na obrazie. Nakładki pozostają we własnych playerach.

Ścieżki wszystkich dowodów: `F:/_DEV/Komparator-main/tests/artifacts/preview_overlay/`.

- baseline_window.png — brak telemetrii przed naprawą.
- sibling_window.png, native_sibling_window.png, native_red_window.png — niewystarczające próby QWidget.
- quick_visible_window.png — finalny renderer, dwa overlay nad video.
- lr_t0_window.png, lr_t5570_window.png, lr_t60_window.png — oba filmy w zadanych punktach.
- top_bottom_window.png — Góra/Dół, prawidłowe pozycje na rzeczywistych obrazach.
- resized_window.png, maximized_window.png, fullscreen_window.png — zmiany geometrii.
- red_probe_window.png — czerwone tło i tekst na video.
- five_minute_start_window.png, five_minute_end_window.png — start/koniec pomiaru.
- Odpowiednie *_desktop.png to pełne obrazy rzeczywistego ekranu, *_player1/2.png to GPU framebuffer z video i overlay.

Pomiar widoczności wykorzystuje jasne wnętrza liter nazwy kamery i ich kontrast wobec sąsiedniego tła na desktop screenshot. Nie wymaga identycznego RGB krawędzi antyaliasowanych liter: półprzezroczysty podkład na ruchomym video naturalnie zmienia te piksele. Tekst i obraz sprawdzane razem; czerwony control sprawdza rzeczywiste z-order. Próbkowanie raz/s pozwala wykryć okresowe zanikanie, a stała warstwa z=1 zapewnia współrenderowanie każdej klatki. Kontrola negatywna na zapisanym rzeczywistym baseline bez overlay: kontrast maski liter -0.73/-0.52 (odrzucony); finalny widoczny overlay 219.73/191.52 (zaliczony). Dowód pixel_negative_control.json. Nie deklarujemy pomiaru wszystkich pikseli każdej klatki ani OCR.

## Regresje

4 nowe testy PlayerWidget: aspekt/pillarbox, 100 zmian TIME bez rebuild layoutu, cache/hide, wspólna scena/z-order/przezroczystość/input. Cała dotychczasowa suite również przechodzi. Qt offscreen nie zastępuje rzeczywistego desktop testu; uruchomiono obydwa.

SHA256 przed/po wszystkich native .cpp/.h, preview_sync.py i telemetry*.py: identyczne, 25 plików (dokładny wynik w unchanged_sources_verified.json). MainWindow zmienia tylko overlay_index obu playerów. Native zero-copy smoke: istniejący nieprzebudowany exporter, oba realne źródła, overlay, offset4.423, limit2s. Return0, complete/success, 60 klatek, 87.92fps; download/upload/software=0/0/0. MP4 export_regression.mp4, log export_regression.log.

Zmienione pliki produkcyjne: src/player_widget.py, src/preview_video.qml (nowy), src/main.py (dwa identyfikatory diagnostyczne). Testy: test_player_overlay.py, diagnose_preview_overlay.py, verify_preview_overlay_windows.py. Raport: RAPORT_PREVIEW_TELEMETRY_OVERLAY_FIX.md.

## Wyniki końcowe

Unit tests: **26/26 PASS**, compileall PASS, import main PASS, pyflakes PASS. Rzeczywiste screenshoty Windows w T=0/5.570/60, oba układy i stany okna: PASS. Overlay faktycznie nad obrazem, nie tylko isVisible.

**Nie zaliczono bramki pełnych 5 minut.** Bieg desktopowy doszedł do co najmniej 245.3 s z hard_seek_count=0 i widocznymi glyphami w zapisanych checkpointach, lecz pętla zdarzeń zakończyła się bez wyniku końcowego. Następny bieg zakończył się podczas zmiany flag okna po 0.25 s. Nie ma windows_visibility_results.json potwierdzającego 300 s. Po celowym przerwaniu tury nie uruchomiono kolejnego długiego pomiaru. Harness został zabezpieczony przed automatycznym quit przy rekreacji okna; jawne zamknięcie testu nadal przerywa go z kodem 1. Do dokończenia: python tests/verify_preview_overlay_windows.py --hwaccel amd.

set_overlay: 100 zmian TIME -> 0 zmian videoRect/layout; cache tekstu działa. Pełnych liczników text updates/layout/flicker dla 300 s nie deklarujemy przed zakończeniem pomiaru. Wstępne screenshoty i kontrole z-order pozostają poprawne. Kryterium końcowe całego zadania **nie jest jeszcze spełnione** z powodu brakującego pełnego biegu.

ROOT_CAUSE=QVideoWindow/createWindowContainer przykrywał QLabel mimo poprawnego tekstu/isVisible
QVIDEOWIDGET_NATIVE_SURFACE=YES; wewnętrzny QVideoWindow, niezależny od flag zewnętrznego QWidget
OVERLAY_IMPLEMENTATION=QQuickWidget + VideoOutput + Rectangle/Text w jednej scenie GPU, stałe z=1
GOPRO_OVERLAY_PASS=YES; rzeczywisty ekran T=0/5.570/60
DJI_OVERLAY_PASS=YES; rzeczywisty ekran T=0/5.570/60
TWO_PLAYER_OVERLAY_PASS=YES
TOP_BOTTOM_PASS=YES
LEFT_RIGHT_PASS=YES
OVERLAY_FLICKER_PASS=NOT_FULLY_VERIFIED; brak zanikania w zapisanych checkpointach
FIVE_MINUTE_PREVIEW_PASS=INCOMPLETE; wymagane ponowienie pełnych 300 s
PREVIEW_HARD_SEEK_COUNT=0 w zakończonych checkpointach do 245.3 s
LAYOUT_REBUILD_DURING_OVERLAY_UPDATES=0; automatyczny test 100 zmian TIME
EXPORT_ZERO_COPY_UNCHANGED=YES; źródła identyczne, realny smoke PASS, liczniki0/0/0

