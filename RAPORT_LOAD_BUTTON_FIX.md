# RAPORT: Naprawa przycisku „Wczytaj” w Comparator

Data wykonania: 2026-10-07
Projekt: `SportCamComparator`

---

## 1. Zdiagnozowany problem i Root Cause

### 1.1. Root Cause #1 (Główna przyczyna zablokowania otwierania okna):
Sygnał `QPushButton.clicked` w bibliotece Qt emituje domyślnie sygnał o sygnaturze `clicked(bool checked = false)`.
Podłączenie:
```python
self.btn_load.clicked.connect(self.load_videos)
```
do metody:
```python
def load_videos(self, files=None):
    if files is None:
        files, _ = QFileDialog.getOpenFileNames(...)
    if not files:
        return False
```
powodowało, że kliknięcie przycisku myszą przekazywało jako pierwszy argument pozycyjny wartość `False` (`checked=False`).
W efekcie:
- `files` przyjmowało wartość logiczną `False`,
- warunek `if files is None:` był fałszywy (`False is None -> False`), przez co wywołanie `QFileDialog.getOpenFileNames()` było całkowicie pomijane,
- następny warunek `if not files:` (`not False -> True`) zwracał natychmiast `False` bez żadnego błędu, komunikatu ani akcji.

### 1.2. Root Cause #2 (Priorytet hit-testu zmiany rozmiaru w nativeEvent / WM_NCHITTEST):
W obsłudze `nativeEvent(WM_NCHITTEST)` logika sprawdzania 8-pikselowej ramki zmiany rozmiaru okna (`ly < border -> HTTOP`) była wykonywana przed analizą kontrolek belki tytułowej. Gdy okno nie było zmaksymalizowane, kliknięcia w górną krawędź przycisków w belce tytułowej były przechwytywane przez Windows jako próba rozciągania okna (`HTTOP`), a nie interakcja z kontrolką (`HTCLIENT`).

### 1.3. Rozszerzenie filtrów i zapamiętywanie folderu:
Brakowało uwzględnienia formatu `*.avi` w filtrze plików oraz zmiennej przechowującej ostatnio otwarty folder (`self._last_dir`). Tłumaczenia tytułów dialogu w języku niemieckim i francuskim zostały ujednolicone z wymaganiami.

---

## 2. Wprowadzone poprawki

1. **Dedykowany handler `load_two_videos`**:
   - Utworzono metodę `self.load_two_videos()` jako jednoznaczny slot dla zdarzenia kliknięcia przycisku.
   - W `self.load_videos(self, files=None)` wprowadzono zabezpieczenie:
     `if files is None or isinstance(files, bool):`
     co gwarantuje poprawne otwarcie dialogu nawet w przypadku bezpośredniego wywołania z sygnału `clicked(bool)`.
   - Zapewniono pojedyncze podłączenie sygnału oraz aliasy `self.load_button` i `self.title_bar.load_button`.

2. **Hierarchia hit-testu w `nativeEvent` (`WM_NCHITTEST`)**:
   - Dodano metodę pomocniczą `_is_interactive_titlebar_control(widget)`, która sprawdza, czy dany widget lub jego rodzic w belce tytułowej jest kontrolką interaktywną (`QPushButton`, `QComboBox`, `QAbstractSpinBox`, `QLineEdit`, `QCheckBox`, `QToolButton`).
   - W `nativeEvent`:
     1. W pierwszej kolejności weryfikowane są kontrolki belki tytułowej – jeśli kursor znajduje się nad przyciskiem, polem wyboru lub spinboxem, zwracany jest `HTCLIENT`.
     2. Dla przycisku maksymalizacji zwracany jest `HTMAXBUTTON` (Windows 11 Snap Layouts).
     3. Dopiero dla obszarów niebędących kontrolkami interaktywnymi sprawdzana jest ramka zmiany rozmiaru (`HTTOP`, `HTLEFT`, narożniki itd.).
     4. Pozostały pusty obszar belki oraz etykieta tytułu zwracają `HTCAPTION` (przeciąganie okna i dwuklik).

3. **Usprawnienia QFileDialog i transakcyjność**:
   - Dialog wywoływany jest zawsze na głównym wątku Qt GUI.
   - Zapamiętywany jest ostatnio wybrany folder (`self._last_dir`).
   - Dodano pełne filtry: `*.mp4 *.mov *.mkv *.avi` oraz `*.*`.
   - Walidacja dokładnie 2 plików:
     - 0 plików (anulowanie) $\rightarrow$ ciche wyjście bez błędów.
     - 1 plik $\rightarrow$ zlokalizowany komunikat `load_two_files_required`.
     - 3+ pliki $\rightarrow$ zlokalizowany komunikat `load_two_files_required`.
     - 2 pliki $\rightarrow$ transakcyjne załadowanie obu odtwarzaczy i uruchomienie telemetrii.

4. **Lokalizacja we wszystkich językach (`src/i18n.py`)**:
   - PL: `load_videos_title`: "Wybierz dwa pliki wideo", `video_filter`: "Wideo (*.mp4 *.mov *.mkv *.avi);;Wszystkie pliki (*.*)"
   - EN: `load_videos_title`: "Select two video files", `video_filter`: "Video files (*.mp4 *.mov *.mkv *.avi);;All files (*.*)"
   - DE: `load_videos_title`: "Zwei Videodateien auswählen", `video_filter`: "Videodateien (*.mp4 *.mov *.mkv *.avi);;Alle Dateien (*.*)"
   - FR: `load_videos_title`: "Sélectionner deux fichiers vidéo", `video_filter`: "Fichiers vidéo (*.mp4 *.mov *.mkv *.avi);;Tous les fichiers (*.*)"

---

## 3. Wyniki testów i weryfikacji

- **Testy jednostkowe (`python -m pytest tests/`)**:
  - `tests/test_comparator_gui_and_options.py` (11 passed)
  - Pełny pakiet testów: **66 passed, 1 skipped in 9.22s**.
- **Kompilacja (`python -m compileall -q src`)**:
  - **0 błędów**.
- **Testy interaktywne i hit-test**:
  - Wszystkie kontrolki górnej belki (`Wczytaj`, `layout_mode`, `audio_combo`, `decoder_combo`, `Eksport`, `preset_combo`, `encoder_combo`, `bitrate_spin`, `scale_combo`, `Opcje`, `Minimalizuj`, `Zamknij`) zwracają `HTCLIENT`.
  - Przycisk `Maksymalizuj` zwraca `HTMAXBUTTON`.
  - Pusty obszar belki i etykieta tytułu zwracają `HTCAPTION`.

---

## 4. Podsumowanie kluczy akceptacyjnych (Acceptance Keys)

LOAD_BUTTON_SIGNAL_CONNECTED=YES
LOAD_BUTTON_CLICK_EVENT_RECEIVED=YES
LOAD_BUTTON_WIDGET_AT_CURSOR=YES
LOAD_BUTTON_HITTEST=HTCLIENT
FILE_DIALOG_OPENS=YES
FILE_DIALOG_GUI_THREAD=YES
TWO_FILES_SELECTION_PASS=YES
CANCEL_PASS=YES
ONE_FILE_VALIDATION_PASS=YES
THREE_FILES_VALIDATION_PASS=YES

OPTIONS_BUTTON_PASS=YES
EXPORT_BUTTON_PASS=YES
COMBOBOXES_PASS=YES
TITLEBAR_DRAG_PASS=YES
TITLEBAR_DOUBLECLICK_PASS=YES
SNAP_LAYOUT_PASS=YES

PL_PASS=YES
EN_PASS=YES
DE_PASS=YES
FR_PASS=YES

ROOT_CAUSE=QPushButton.clicked emits bool checked=False as first argument into load_videos(self, files=None), causing files to evaluate as False instead of None, which bypassed QFileDialog and returned False immediately; additionally WM_NCHITTEST resize border check took precedence over controls.
FIX=Added dedicated load_two_videos handler, guarded boolean parameter in load_videos, implemented _is_interactive_titlebar_control with top hit-test priority for HTCLIENT, added video_filter localization and session last directory tracking.
UNIT_TESTS=66 passed, 1 skipped
FINAL_STATUS=RESOLVED
