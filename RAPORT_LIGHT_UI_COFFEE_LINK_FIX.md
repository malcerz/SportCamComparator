# RAPORT: Jasny interfejs Comparator oraz lokalizacja linku „Postaw mi kawę”

Data wykonania: 2026-10-07
Projekt: `SportCamComparator`

---

## 1. Klucze akceptacyjne (Acceptance Summary)

| Parametr / Wymóg | Wartość | Status |
|---|---|---|
| `COFFEE_LINK_IN_MAIN_WINDOW` | `NO` | PASS |
| `EMPTY_FOOTER_IN_MAIN_WINDOW` | `NO` | PASS |
| `COFFEE_LINK_IN_OPTIONS_DIALOG` | `YES` | PASS |
| `LIGHT_THEME_WINDOWS_NATIVE` | `YES` | PASS |
| `I18N_LOCALIZATION_ALL_LOCALES` | `YES` | PASS |
| `ALL_TESTS_PASSING` | `YES` (64 passed, 1 skipped) | PASS |
| `COMPILEALL_STATUS` | `OK` (0 errors) | PASS |

---

## 2. Podsumowanie wprowadzonych zmian

### 2.1. Całkowite usunięcie linku i stopki z Okna Głównego (`MainWindow`)
- **Usunięte elementy**:
  - `QLabel` z linkiem `buycoffee.to`,
  - `footer_row` (`QHBoxLayout`),
  - marginesy, spacery i separatory dolne dodane dla linku.
- **Układ dolny okna**:
  - `MainWindow` kończy się bezpośrednio na sekcji seekbarów i kontrolek timeline (`seekbar_area`).
  - Brak jakiegokolwiek pustego paska, statusu czy odstępu na dole okna głównego (`EMPTY_FOOTER_IN_MAIN_WINDOW=NO`).

### 2.2. Przeniesienie linku wyłącznie do okna Opcji (`OptionsDialog`)
- **Lokalizacja**: Link znajduje się wyłącznie w dialogu `Opcje` na samym dole.
- **Hierarchia komponentów w oknie Opcje**:
  1. Sekcja grupy `Nakładka` (suwaki wielkości fontu 50%–200% i krycia 0%–100%)
  2. Sekcja grupy `Comparator` (checkbox dopełniania do 4K czarnymi pasami)
  3. Poziomy separator (`QFrame.Shape.HLine`)
  4. Wiersz linku:
     - Etykieta: `Postaw mi kawę:` (zlokalizowana)
     - Klikalny odnośnik: `https://buycoffee.to/malcerz` z `openExternalLinks=True` oraz flagą `TextBrowserInteraction`
  5. Przyciski akcji: `[ OK ]` `[ Anuluj ]`
- **DPI i skalowanie**:
  - Dialog ma elastyczny `sizeHint` i bezpieczną szerokość bazową (`460px+`), dzięki czemu link nie jest ucinany ani przysłaniany przy DPI 100%, 125% i 150% we wszystkich językach (w tym w najdłuższym niemieckim).

### 2.3. Pełna lokalizacja linku (`src/i18n.py`)
Dodano klucz `buy_coffee_prompt` dla wszystkich 4 obsługiwanych języków:
- **PL**: `Postaw mi kawę:`
- **EN**: `Buy me a coffee:`
- **DE**: `Spendiere mir einen Kaffee:`
- **FR**: `Offrez-moi un café :`
- **URL** we wszystkich wersjach: `https://buycoffee.to/malcerz`

### 2.4. Jasny, natywny wygląd Windows (Usunięcie ciemnego arkusza stylów)
- Usunięto ciemny arkusz stylów (`#1e1e1e`, `#2d2d2d`, biały tekst) z belki górnej (`CustomTitleBar`).
- Zastosowano natywny, jasny styl Windows 11:
  - Tło belki górnej: `#f3f3f3` z subtelną krawędzią dolną `#dcdcdc`,
  - Tytuł programu `Comparator`: czarny/ciemny (`#1a1a1a`), bold 13px,
  - Przyciski i listy rozwijane (`QPushButton`, `QComboBox`, `QDoubleSpinBox`):
    - Jasne tło (`#ffffff`),
    - Ciemny tekst (`#1a1a1a`),
    - Subtelna krawędź (`#cccccc`), hover (`#f0f0f0`), stan nieaktywny (`#f5f5f5` / tekst `#888888`),
    - Menu rozwijane (`QAbstractItemView`): białe tło z ciemnym tekstem i selekcją `#0078d4`,
  - Przycisk `Eksport`: wyróżniony estetycznym akcentem `#0078d4` z białym tekstem,
  - Przyciski systemowe okna (`Minimalizuj`, `Maksymalizuj`, `Zamknij`):
    - Domyślnie przezroczyste z ciemnymi symbolami,
    - Hover dla min/max: `#e5e5e5`,
    - Hover dla zamknij: `#e81123` z białym krzyżykiem.

---

## 3. Zmodyfikowane pliki

1. [`src/i18n.py`](file:///F:/_DEV/Komparator-main/src/i18n.py):
   - Dodano tłumaczenia `buy_coffee_prompt` dla PL, EN, DE, FR.
2. [`src/options_dialog.py`](file:///F:/_DEV/Komparator-main/src/options_dialog.py):
   - Dodano separator `QFrame`, etykietę `lbl_coffee_prompt` oraz klikalny link `lbl_coffee_link` przed przyciskami dialogu.
3. [`src/main.py`](file:///F:/_DEV/Komparator-main/src/main.py):
   - Usunięto `footer_row` i `lbl_coffee` z `MainWindow`.
   - Zastąpiono ciemny arkusz stylów `CustomTitleBar` jasnym stylem zgodnym z natywnym interfejsem Windows 11.
4. [`tests/test_comparator_gui_and_options.py`](file:///F:/_DEV/Komparator-main/tests/test_comparator_gui_and_options.py):
   - Zaktualizowano testy: potwierdzenie braku linku w `MainWindow` (`test_coffee_link_absent_from_main_window`) oraz obecności wyłącznie w `OptionsDialog` (`test_coffee_link_only_in_options_dialog`) wraz z walidacją tłumaczeń we wszystkich 4 językach.

---

## 4. Weryfikacja testowa i wizualna

1. **Kompilacja i składnia**:
   ```powershell
   python -m compileall -q src
   # Wynik: 0 błędów
   ```

2. **Zestaw testów jednostkowych**:
   ```powershell
   python -m pytest tests/
   # Wynik: 64 passed, 1 skipped in 9.35s
   ```

3. **Wygenerowane zrzuty ekranu**:
   - `build/mainwindow_real.png` – czysty, jasny interfejs z natywnymi kontrolkami, brak stopki na dole.
   - `build/options_real_pl.png` – dialog opcji z separatorem i zlokalizowanym linkiem (PL).
   - `build/options_real_de.png` – dialog opcji w języku niemieckim (najdłuższy tekst promocyjny, brak obcięć tekstu).
   - `build/options_real_en.png` – dialog opcji w języku angielskim.
