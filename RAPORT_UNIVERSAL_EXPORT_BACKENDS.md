# RAPORT: Uniwersalny Podsystem Eksportu HEVC (Komparator)

Data weryfikacji: 2026-10-06
Projekt: `SportCamComparator`
Środowisko testowe: Windows 11, Intel Core i5-12400 (UHD 730) + NVIDIA Quadro P400 (Pascal), sterownik NVIDIA 582.78 (NVENC API 13.0)

---

## 1. Zidentyfikowane Problemy i Root Cause

### 1.1 Intel QSV (D3D11 Zero-Copy vs Legacy)
- **Objaw:** Wcześniejszy błąd `Specified pixel format d3d11 is not supported by the hevc_qsv encoder`. Po wdrożeniu ramek sprzętowych QSV (AV_PIX_FMT_QSV), próba derywacji kontekstu QSV z kontekstu D3D11VA w FFmpeg 9.0.1 (oneVPL) kończyła się błędem `Error setting child device handle: -16` (`MFX_ERR_UNSUPPORTED`).
- **Rozwiązanie w kodzie natywnym:** Wprowadzono strukturalny kod błędu probe: `QSV_PIXFMT_INTEROP_FAILED`.
- **Ścieżka produkcyjna:** W trybie **AUTO**, wykrycie `QSV_PIXFMT_INTEROP_FAILED` powoduje bezbłędne i natychmiastowe przejście do **Próby 2 (Legacy Intel `hevc_qsv`)** na wspólnym `bin/ffmpeg.exe`, która na obecnym Intel UHD 730 inicjalizuje sprzętowy encoder i generuje poprawny plik HEVC.

### 1.2 NVIDIA NVENC (Quadro P400 / Pascal / Driver 582.78)
- **Objaw:** Wspólny FFmpeg 9.0.1 wymaga `NVENC API 13.1` (sterownik `>=610.00`), podczas gdy sterownik 582.78 na architekturze Pascal (Quadro P400) udostępnia `NVENC API 13.0`. Powodowało to błąd `Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0`.
- **Rozwiązanie w kodzie natywnym:** Wprowadzono kod błędu probe: `NVENC_API_MISMATCH`.
- **Vendor-Isolated Runtime:** Wdrożono dedykowany katalog `runtime/nvidia/ffmpeg/` z binariami FFmpeg kompatybilnymi z NVENC API 13.0 (sprawdzony build FFmpeg 8.1.2).
- **Ścieżka produkcyjna:** W trybie **AUTO**, po wykryciu `NVENC_API_MISMATCH`, program przechodzi do **Próby 2 (Legacy NVIDIA `hevc_nvenc`)** na `runtime/nvidia/ffmpeg/ffmpeg.exe`, co na obecnym Quadro P400 bezbłędnie przeprowadza sprzętowy eksport HEVC.

### 1.3 AMD AMF (D3D11 Zero-Copy)
- **Stan:** D3D11 zero-copy compositor -> D3D11 hardware surface -> `hevc_amf` pozostaje nienaruszony.
- **Zero-Copy Gate:** Zachowano bezwzględny wymóg zerowych liczników buforowania CPU:
  - `FULL_FRAME_HWDOWNLOAD_COUNT=0`
  - `FULL_FRAME_HWUPLOAD_COUNT=0`
  - `SOFTWARE_VIDEO_FRAME_COUNT=0`

### 1.4 Centralny Resolver Helperów i CWD Independence
- Wyeliminowano relatywne ścieżki i podatność na CWD (`Path("bin/...")`).
- Wprowadzono funkcję `get_app_root()` w `src/video_encoder.py`, która precyzyjnie kotwiczy wszystkie ścieżki do katalogu głównego projektu niezależnie od katalogu wywołania (`src/`, katalog nadrzędny lub temp).

---

## 2. Ścieżki Artefaktów i Resolver

```ini
COMMON_HELPER_BUILT_PATH=<project-root>\bin\KomparatorGpuExporter.exe
NVIDIA_HELPER_BUILT_PATH=<project-root>\bin\KomparatorGpuExporterNvidia.exe
PYTHON_COMMON_SEARCH_PATH=<project-root>\bin\KomparatorGpuExporter.exe
PYTHON_NVIDIA_SEARCH_PATH=<project-root>\bin\KomparatorGpuExporterNvidia.exe
```

- `.\build_gpu_exporter.ps1 -Clean` -> buduje i dostarcza `bin\KomparatorGpuExporter.exe` (Exit Code 0).
- `.\build_gpu_exporter_nvidia_compat.ps1 -Clean` -> buduje i dostarcza `bin\KomparatorGpuExporterNvidia.exe` (Exit Code 0).
- Runtime DLLs (`libstdc++-6.dll`, `libgcc_s_seh-1.dll`, `libwinpthread-1.dll`, `avcodec-63.dll`, etc.) są weryfikowane i dostarczane bezpośrednio do `bin/`.

---

## 3. Wykryty Sprzęt na Maszynie Testowej

- **GPU 1:** `Intel(R) UHD Graphics 730`
  - Vendor ID: `0x8086`
  - Device ID: `0x4692`
  - LUID: `00000000:0000c7e3`
  - Sterownik: `32.0.101.7088`
- **GPU 2:** `NVIDIA Quadro P400` (Pascal, CC 6.1)
  - Vendor ID: `0x10DE`
  - Device ID: `0x1CB3`
  - LUID: `00000000:0000b716`
  - Sterownik: `582.78` (NVENC API 13.0)

W `D3D11Context.cpp` zaimplementowano jawną enumerację adapterów DXGI według `VendorId` (AMD `0x1002`, Intel `0x8086`, NVIDIA `0x10DE`) i bezpośrednie tworzenie urządzenia na wybranym adapterze sprzętowym (`D3D_DRIVER_TYPE_UNKNOWN`).

---

## 4. Macierz Decyzyjna Podsystemu Eksportu

### 4.1 Hierarchia AUTO (backend = 0)
1. **Próba 1:** D3D11 Zero-Copy na wybranym GPU (sprawdzenie helpera i probe JSON).
   - Jeśli PASS -> użycie natywnego D3D11 Zero-Copy (`AMD_AMF_D3D11`, `INTEL_QSV_D3D11`, `NVIDIA_D3D11`).
   - Jeśli FAIL -> rejestracja przyczyny i płynne przejście do Próby 2.
2. **Próba 2:** Sprzętowy enkoder Legacy FFmpeg tego samego producenta (`hevc_amf`, `hevc_qsv`, `hevc_nvenc`).
   - Jeśli PASS -> użycie dedykowanego FFmpeg (`AMD_AMF_LEGACY`, `INTEL_QSV_LEGACY`, `NVIDIA_LEGACY`).
   - Jeśli FAIL -> rejestracja i płynne przejście do Próby 3.
3. **Próba 3:** CPU HEVC / `libx265` na wspólnym `bin/ffmpeg.exe`.
   - Jeśli PASS -> użycie enkodera programowego (`CPU_X265`).
   - Dopiero w razie niepowodzenia wszystkich 3 prób zgłaszany jest błąd użytkownikowi.

### 4.2 Wymuszone D3D11 (backend = 1)
- Próba wyłącznie ścieżki D3D11 Zero-Copy.
- W razie niepowodzenia: natychmiastowe zgłoszenie precyzyjnego błędu diagnostycznego z kodem przyczyny (np. `QSV_PIXFMT_INTEROP_FAILED`, `NVENC_API_MISMATCH`, `AMF_ENCODER_OPEN_FAILED`).
- **BRAK cichego przejścia do Legacy lub CPU.**

### 4.3 Wymuszone Legacy (backend = 2)
- Pominięcie helpera D3D11.
- Próba sprzętowego enkodera wybranego vendora w FFmpeg CLI, z ewentualnym fallbackiem do CPU `libx265`.

---

## 5. Profile Kompresji GUI

Wszystkie profile GUI mapują się na rzeczywiste flagi vendorów wyłącznie dla kodeka HEVC:

| Profil GUI | libx265 | AMD AMF | NVIDIA NVENC | Intel QSV |
|---|---|---|---|---|
| **Najszybszy** | `-preset veryfast` | `-quality speed` | `-preset p2` | `-preset faster` |
| **Zbalansowany** | `-preset medium` | `-quality balanced` | `-preset p4` | `-preset medium` |
| **Najlepsza jakość** | `-preset slow` | `-quality quality` | `-preset p6` | `-preset slow` |

- **HEVC Only:** Kodek H.264 został całkowicie wycofany.
- **Orientacja:** Wymuszenie `rotate=0` w strumieniu wyjściowym zapobiega obracaniu wideo przez odtwarzacze.

---

## 6. Wyniki Testów Rzeczywistych na Sprzęcie

Wykonano rzeczywiste eksporty wideo na fizycznym sprzęcie testowym:

1. **Intel QSV (AUTO):**
   - Probe D3D11: `QSV_PIXFMT_INTEROP_FAILED`
   - Fallback AUTO: `INTEL_QSV_LEGACY` (`bin/ffmpeg.exe -c:v hevc_qsv`)
   - Wynik: **PASS** (wygenerowano poprawny plik HEVC Main, 326 185 bajtów).
2. **NVIDIA (AUTO):**
   - Probe D3D11: `NVENC_API_MISMATCH`
   - Fallback AUTO: `NVIDIA_LEGACY` (`runtime/nvidia/ffmpeg/ffmpeg.exe -c:v hevc_nvenc`)
   - Wynik: **PASS** (wygenerowano poprawny plik HEVC Main, 405 882 bajty).
3. **CPU (AUTO):**
   - Wybór AUTO: `CPU_X265` (`bin/ffmpeg.exe -c:v libx265`)
   - Wynik: **PASS** (wygenerowano poprawny plik HEVC Main, 401 809 bajtów).
4. **Wymuszone D3D11 na Intel QSV:**
   - Wynik: **PASS** (zgłoszono jawny wyjątek `D3D11 Zero-Copy niedostępny dla Intel QSV [QSV_PIXFMT_INTEROP_FAILED]` bez cichego fallbacku).
5. **Wymuszone D3D11 na NVIDIA:**
   - Wynik: **PASS** (zgłoszono jawny wyjątek `D3D11 Zero-Copy niedostępny dla NVIDIA [NVENC_API_MISMATCH]` bez cichego fallbacku).

---

## 7. Wyniki Testów Automatycznych (Pytest)

```text
============================= test session starts =============================
rootdir: SportCamComparator
collected 44 items

tests\test_export_live_preview.py .....                                  [ 11%]
tests\test_export_preview.py .......s...                                 [ 36%]
tests\test_player_overlay.py ....                                        [ 45%]
tests\test_telemetry_dji.py ...........                                  [ 70%]
tests\test_universal_export_backends.py .............                    [100%]

======================== 43 passed, 1 skipped in 4.73s ========================
```

Wszystkie 13 testów jednostkowych nowej matrycy decyzyjnej (`test_universal_export_backends.py`) zakończyło się statusem **PASSED**:
- `test_helper_resolution_never_uses_cwd` PASSED
- `test_resolve_legacy_ffmpeg` PASSED
- `test_matrix_cpu_only` PASSED
- `test_matrix_amd_d3d11_pass` PASSED
- `test_matrix_amd_d3d11_fail_legacy_pass` PASSED
- `test_matrix_amd_all_fail_cpu_pass` PASSED
- `test_matrix_intel_d3d11_pass` PASSED
- `test_matrix_intel_d3d11_fail_legacy_pass` PASSED
- `test_matrix_intel_all_fail_cpu_pass` PASSED
- `test_matrix_nvidia_d3d11_pass` PASSED
- `test_matrix_nvidia_api_mismatch_legacy_compat_pass` PASSED
- `test_matrix_nvidia_all_fail_cpu_pass` PASSED
- `test_forced_d3d11_fails_cleanly_without_silent_fallback` PASSED
