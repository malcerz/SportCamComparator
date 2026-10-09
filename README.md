# SportCamComparator

SportCamComparator odtwarza, synchronizuje i porównuje dwa nagrania z kamer sportowych. Obsługuje podgląd obok siebie i góra/dół, telemetrię GPMF, synchronizację audio oraz eksport z nakładkami.

## Funkcje

- Podgląd dwóch nagrań z regulacją synchronizacji i prędkości odtwarzania.
- Odczyt telemetrii GoPro i DJI oraz nakładki w podglądzie i eksporcie.
- Sprzętowe ścieżki eksportu NVIDIA Modern/Legacy, AMD D3D11VA→AMF oraz Intel QSV, z eksportem CPU jako ścieżką awaryjną.
- Eksport D3D11 Zero-Copy z obsługą P010, HLG/BT.2020, rotacji i nakładek BGRA.
- Podgląd eksportu i dopasowanie proporcji obrazu oraz paddingu.

## Wymagania

- Windows 10/11 i Python 3.10 lub nowszy.
- FFmpeg `ffmpeg` i `ffprobe` w `PATH` dla odtwarzania, analizy i ścieżek eksportu korzystających z FFmpeg CLI.
- Sterownik GPU obsługujący wybraną ścieżkę sprzętową. NVIDIA, AMD i Intel mają różne możliwości kodowania; dostępna jest też ścieżka CPU.

## Uruchomienie z kodu

```powershell
git clone https://github.com/malcerz/SportCamComparator.git
cd SportCamComparator
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python src\main.py
```

Jeśli PowerShell blokuje aktywację środowiska, pomiń ją i uruchom `.venv\Scripts\python.exe` bezpośrednio.

## Kompilacja natywnego eksportera D3D11

Eksporter wymaga Windows SDK, CMake, kompilatora C++17 (Visual Studio C++ Build Tools albo GCC/MinGW), Ninja przy GCC oraz współdzielonego pakietu deweloperskiego FFmpeg. Pakiet musi zawierać `include`, `lib` i `bin` z bibliotekami runtime zgodnymi z nagłówkami. Build sprawdzono z FFmpeg 9.0.1 (`libavcodec` 63); pobierz pakiet `full shared` ze [strony buildów Windows wskazanej przez FFmpeg](https://www.gyan.dev/ffmpeg/builds/) i użyj zgodnej wersji bibliotek.

Gotowe biblioteki FFmpeg i lokalne runtime nie są commitowane. Pobierz współdzielony pakiet deweloperski FFmpeg dla Windows i ustaw `FFMPEG_DIR` na jego katalog główny. Możesz też umieścić go w `third_party/ffmpeg` (ten lokalny katalog jest ignorowany przez Git).

```powershell
$env:FFMPEG_DIR = 'C:\deps\ffmpeg-shared'
Set-ExecutionPolicy -Scope Process Bypass
.\build_gpu_exporter.ps1 -Configuration Release
```

Wynik pojawi się w `bin\KomparatorGpuExporter.exe`. Dostępne urządzenia i enkodery sprawdzisz poleceniem:

```powershell
& .\bin\KomparatorGpuExporter.exe --probe
```

Skrypt NVIDIA Compat wykonuje ten sam build i tworzy dodatkową nazwę `KomparatorGpuExporterNvidia.exe`:

```powershell
.\build_gpu_exporter_nvidia_compat.ps1 -Configuration Release
```

## Testy

```powershell
python -m compileall -q src tests
python -m pytest -q
```

Testy GPU wymagają obsługiwanego sprzętu i sterowników. Testy sprzętu, którego nie ma w systemie, są pomijane.

## Zasoby i raporty techniczne

Zrzuty ekranu interfejsu znajdują się w `assets/`. Pliki `RAPORT_*.md` opisują poprawki, testy sprzętowe i decyzje dotyczące potoku eksportu. Przykładowe filmy, wygenerowane binaria, logi i lokalne środowiska są wykluczone z repozytorium.

Kod Python korzysta z pakietów wymienionych w `requirements.txt`; SciPy jest opcjonalne i poprawia filtrację w AutoSync. Eksporter natywny korzysta z FFmpeg shared development package, nagłówków NVIDIA NVENC i Intel oneVPL w `native/third_party`, Windows SDK oraz Direct3D 11.

Jeśli program jest przydatny, możesz postawić mi kawę: [buycoffee.to/malcerz](https://buycoffee.to/malcerz).
