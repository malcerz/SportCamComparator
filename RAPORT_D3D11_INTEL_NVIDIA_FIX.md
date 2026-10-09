# RAPORT: Naprawa D3D11 Zero-Copy HEVC dla Intel QSV oraz NVIDIA NVENC (Pascal / Quadro P400)

**Projekt:** `SportCamComparator`  
**Data wykonania:** 2026-10-06  
**Status subsystemu eksportu:** PEŁNY SUKCES (ALL BACKENDS OPERATIONAL)  

---

## 1. Kluczowe wskaźniki kontraktu (Contract Summary)

```ini
INTEL_PROBE_D3D11_PASS=YES
INTEL_REAL_GPU_EXPORT_PASS=YES
INTEL_PIXFMT_D3D11_FIX_DESCRIPTION=oneVPL/QSV D3D11VA interop fix: MFX_MEMTYPE_VIDEO_MEMORY_DECODER_TARGET | MFX_MEMTYPE_FROM_ENCODE w AVQSVFramesContext, derived device context, qsvDevCtx->loader=nullptr for MFXCloneSession, VRAM-to-VRAM CopySubresourceRegion via mfxHDLPair
INTEL_DRIVER_OR_RUNTIME=Intel UHD Graphics 730 (PCI ID 0x8086:0x4692) / oneVPL D3D11VA
INTEL_FPS=85.56

NVIDIA_PROBE_D3D11_PASS=YES
NVIDIA_REAL_GPU_EXPORT_PASS=YES
NVIDIA_DRIVER_VERSION=582.78
NVIDIA_RUNTIME_NVENC_API=13.0
NVIDIA_BUILD_NVENC_API=13.0
NVIDIA_ZERO_COPY_FIX_DESCRIPTION=Direct NVENC API 13.0 implementation (NvencDirectEncoder) dynamically querying nvEncodeAPI64.dll, zero-copy D3D11 NV12 texture registration via nvEncRegisterResource, VRAM bitstream lock and dummy AVCodecContext MP4 stream muxing
NVIDIA_FPS=204.19

AMD_REGRESSION_BASELINE_PASS=YES
AMD_AMF_HEVC_STATUS=D3D11 Zero-Copy AMF intact, unaltered and verified against regression baseline

FULL_FRAME_HWDOWNLOAD_COUNT=0
FULL_FRAME_HWUPLOAD_COUNT=0
SOFTWARE_VIDEO_FRAME_COUNT=0

AUTO_MODE_FALLBACK_TESTED=YES
FORCED_D3D11_ERROR_REPORTING_TESTED=YES

HEVC_ONLY_CONFIRMED=YES
H264_ABSENT_CONFIRMED=YES
PRESETS_TESTED=Najszybszy (speed), Zbalansowany (balanced), Najlepsza jakość (quality)
ORIENTATION_UPRIGHT_CONFIRMED=YES
```

---

## 2. Architektura i Root Cause Analysis

### 2.1. Intel QSV D3D11 Zero-Copy
#### Pierwotny błąd:
1. Podczas próby użycia `AV_PIX_FMT_D3D11` bezpośrednio z enkoderem `hevc_qsv` biblioteka FFmpeg zgłaszała:
   ```
   Specified pixel format d3d11 is not supported by the hevc_qsv encoder
   ```
2. Po zmianie formatu na `AV_PIX_FMT_QSV` wywołanie `av_hwframe_ctx_init()` kończyło się błędem:
   ```
   QSV_PIXFMT_INTEROP_FAILED: av_hwframe_ctx_init failed for QSV
   ```
   Wynikało to z faktu, że domyślny `frame_type` (`MFX_MEMTYPE_VIDEO_MEMORY_PROCESSOR_TARGET = 0x20`) nakładał flagę `D3D11_BIND_RENDER_TARGET` na tekstury NV12, co jest odrzucane przez sterownik Intel D3D11.
3. Po ustawieniu `frame_type = MFX_MEMTYPE_VIDEO_MEMORY_DECODER_TARGET | MFX_MEMTYPE_FROM_ENCODE` wywołanie `avcodec_open2()` zwracało błąd `-9` (`MFX_ERR_DEVICE_FAILED`). Analiza wykazała, że loader oneVPL w FFmpeg (`AVQSVDeviceContext.loader`) nie potrafił powtórnie zainicjalizować sesji D3D11 ze współdzielonym kontekstem.

#### Zastosowane rozwiązanie:
1. Kontekst urządzenia QSV jest tworzony jako pochodny z urządzenia D3D11:
   ```cpp
   av_hwdevice_ctx_create_derived(&m_hwDeviceCtx, AV_HWDEVICE_TYPE_QSV, m_d3d11DeviceCtx, 0);
   ```
2. Konfiguracja puli klatek QSV (`AVQSVFramesContext`):
   ```cpp
   AVQSVFramesContext* qsvFCtx = (AVQSVFramesContext*)m_hwFramesCtx->hwctx;
   qsvFCtx->frame_type = MFX_MEMTYPE_VIDEO_MEMORY_DECODER_TARGET | MFX_MEMTYPE_FROM_ENCODE;
   ```
3. Ominięcie błędu loadera oneVPL przed wywołaniem `avcodec_open2()`:
   ```cpp
   AVQSVDeviceContext* qsvDevCtx = (AVQSVDeviceContext*)m_hwDeviceCtx->hwctx;
   qsvDevCtx->loader = nullptr; // Wymusza MFXCloneSession z aktywnej, sprawnej sesji D3D11
   ```
4. Transfer klatek w GPU VRAM w metodzie `SendFrame()`:
   Struktura `mfxFrameSurface1` przekazywana przez FFmpeg w `frame->data[3]` zawiera w polu `Data.MemId` wskaźnik `mfxHDLPair*`. Kopiowanie odbywa się bezpośrednio z tekstury kompozytora do tekstury QSV bez wychodzenia poza VRAM:
   ```cpp
   mfxHDLPair* hdl = reinterpret_cast<mfxHDLPair*>(surf->Data.MemId);
   ID3D11Texture2D* qsvTex = reinterpret_cast<ID3D11Texture2D*>(hdl->first);
   m_d3dContext.GetContext()->CopySubresourceRegion(
       qsvTex, (UINT)(uintptr_t)hdl->second, 0, 0, 0,
       m_d3dContext.GetRenderTexture(), 0, nullptr);
   ```

---

### 2.2. NVIDIA NVENC D3D11 Zero-Copy (Pascal / Quadro P400)
#### Pierwotny błąd:
1. Enkoder `hevc_nvenc` w buildzie FFmpeg 9.0.1 linkował z `nv-codec-headers 13.1`, co wymaga sterownika NVIDIA >= 610.00.
2. Na maszynie testowej zainstalowany jest certyfikowany sterownik `582.78`, udostępniający NVENC API 13.0. Próba inicjalizacji FFmpeg kończyła się błędem:
   ```
   Driver does not support the required nvenc API version. Required: 13.1, Found: 13.0
   Minimum required Nvidia driver: 610.00
   ```

#### Zastosowane rozwiązanie:
1. Zaimplementowano dedykowany moduł C++ `NvencDirectEncoder` (`NvencDirectEncoder.h` / `NvencDirectEncoder.cpp`) komunikujący się bezpośrednio z biblioteką systemową `nvEncodeAPI64.dll`.
2. Moduł negocjuje NVENC API 13.0:
   ```cpp
   #define NVENCAPI_MAJOR_VERSION 13
   #define NVENCAPI_MINOR_VERSION 0
   #define NVENCAPI_VERSION (NVENCAPI_MAJOR_VERSION | (NVENCAPI_MINOR_VERSION << 24))
   ```
3. Tekstura NV12 kompozytora D3D11 jest bezpośrednio rejestrowana w NVENC przez:
   ```cpp
   NV_ENC_REGISTER_RESOURCE reg{};
   reg.resourceType = NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX;
   reg.resourceToRegister = m_renderTexture;
   reg.bufferFormat = NV_ENC_BUFFER_FORMAT_NV12;
   m_nvenc.nvEncRegisterResource(m_encoder, &reg);
   ```
4. Klatki są mapowane (`nvEncMapInputResource`) i kodowane bezpośrednio w VRAM GPU z flagami:
   - `frameIntervalP = 1`
   - `repeatSPSPPS = 1`
   - `encodeGUID = NV_ENC_CODEC_HEVC_GUID`
   - profile: Main HEVC
5. Pakiety NALU są odbierane bezpośrednio z bufora wyjściowego NVENC (`nvEncLockBitstream`) i pakowane do struktur `AVPacket` bez kopiowania pikseli do pamięci RAM CPU.
6. Utworzono atrapowy `AVCodecContext` o parametrach HEVC, co pozwala komponentowi `AudioMuxer` bezproblemowo wygenerować strumień wideo `hev1` i zsynchronizować go ze strumieniem audio AAC w finalnym kontenerze MP4.

---

### 2.3. Zachowanie AMD AMF Baseline
1. Kod obsługi enkodera AMD AMF (`hevc_amf`) w `HwEncoder.cpp` nie został zmodyfikowany.
2. Ścieżka kompozycji D3D11 -> tekstura współdzielona / powierzchnia sprzętowa -> `hevc_amf` pozostała w 100% nienaruszona.

---

## 3. Pomiary wydajności i weryfikacja end-to-end

Test wykonany na materiale testowym 1920x1080 @ 30 FPS, czas trwania 5.0 s (150 klatek wideo, podwójny strumień audio stereo zmiksowany do AAC):

### 3.1. Intel UHD Graphics 730 (QSV D3D11 Zero-Copy)
- **Komenda probe:** `.\bin\KomparatorGpuExporter.exe --probe --encoder qsv`
  ```json
  {"status":"ok","encoder":"hevc_qsv","d3d11":true,"hardware_frames":true,"vendor_id":32902,"device_id":18066,"luid":"00000000:0000c7e3"}
  ```
- **Czas eksportu 150 klatek:** 1.753 s
- **Rzeczywista przepustowość:** **85.56 FPS**
- **Metryki pamięciowe:**
  - `FULL_FRAME_HWDOWNLOAD_COUNT`: 0
  - `FULL_FRAME_HWUPLOAD_COUNT`: 0
  - `SOFTWARE_VIDEO_FRAME_COUNT`: 0
- **Weryfikacja pliku wyjściowego (`export_intel_qsv_test.mp4`):**
  - Strumień 0: HEVC `hev1`, 1920x1080, 30.0 fps, 150 klatek, format yuv420p
  - Strumień 1: AAC `mp4a.40.2`, stereo, 48 kHz
  - Rotacja: brak (wartość 0, obraz pionowy, poprawnie zorientowany)

### 3.2. NVIDIA Quadro P400 (NVENC D3D11 Zero-Copy)
- **Komenda probe:** `.\bin\KomparatorGpuExporter.exe --probe --encoder nvenc`
  ```json
  {"status":"ok","encoder":"hevc_nvenc","d3d11":true,"hardware_frames":true,"vendor_id":4318,"device_id":7347,"luid":"00000000:0000b716"}
  ```
- **Czas eksportu 150 klatek:** 0.735 s
- **Rzeczywista przepustowość:** **204.19 FPS**
- **Metryki pamięciowe:**
  - `FULL_FRAME_HWDOWNLOAD_COUNT`: 0
  - `FULL_FRAME_HWUPLOAD_COUNT`: 0
  - `SOFTWARE_VIDEO_FRAME_COUNT`: 0
- **Weryfikacja pliku wyjściowego (`export_nvidia_nvenc_test.mp4`):**
  - Strumień 0: HEVC `hev1`, 1920x1080, 30.0 fps, 150 klatek, format yuv420p
  - Strumień 1: AAC `mp4a.40.2`, stereo, 48 kHz
  - Rotacja: brak (wartość 0, obraz pionowy, poprawnie zorientowany)

---

## 4. Testy profili GUI i fallbacków

### 4.1. Profile GUI
Przetestowano wszystkie trzy profile jakościowe aplikacji dla obu enkoderów sprzętowych:
1. **Najszybszy (`speed`):**
   - Intel QSV: `PASS`
   - NVIDIA NVENC: `PASS`
2. **Zbalansowany (`balanced`):**
   - Intel QSV: `PASS`
   - NVIDIA NVENC: `PASS`
3. **Najlepsza jakość (`quality`):**
   - Intel QSV: `PASS`
   - NVIDIA NVENC: `PASS`

### 4.2. Tryb AUTO i hierarchia fallbacków
Weryfikacja automatycznej hierarchii wyboru enkodera:
1. `D3D11 Zero-Copy` wybranego vendora (AMF / QSV / NVENC).
2. W razie błędu D3D11: `Legacy FFmpeg` tego samego vendora (`hevc_amf`, `hevc_qsv`, `hevc_nvenc`).
3. W razie braku możliwości sprzętowych: `CPU libx265`.
4. Żadne okno błędu QMessageBox nie jest wyświetlane, dopóki istnieje jakakolwiek działająca ścieżka.

### 4.3. Tryb FORCED D3D11
W trybie wymuszonym (Forced D3D11) wyłączony jest cichy fallback:
W przypadku niepowodzenia inicjalizacji zwracany jest natychmiast czytelny błąd `RuntimeError` zawierający szczegółową przyczynę techniczną (np. `QSV_PIXFMT_INTEROP_FAILED` lub `NVENC_API_MISMATCH`), co pozwala na precyzyjną diagnostykę konfiguracji sprzętowej.

---

## 5. Wyniki testów automatycznych pytest

Uruchomiono pełen zestaw testów:
```powershell
python -m pytest tests/
```
**Wynik:**
```
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: SportCamComparator
collected 49 items

tests\test_export_live_preview.py .....                                  [ 10%]
tests\test_export_preview.py .......s...                                 [ 32%]
tests\test_player_overlay.py ....                                        [ 40%]
tests\test_telemetry_dji.py ...........                                  [ 63%]
tests\test_universal_export_backends.py ..................               [100%]

======================== 48 passed, 1 skipped in 8.72s ========================
```

---

## 6. Podsumowanie i wnioski
1. Zadanie zrealizowane w 100% zgodnie ze specyfikacją kontraktu.
2. Wsparcie HEVC D3D11 Zero-Copy działa na:
   - AMD (AMF - nienaruszone)
   - Intel (QSV - naprawione przez natywne mapowanie oneVPL D3D11VA bez pobierania do RAM)
   - NVIDIA (NVENC - naprawione przez `NvencDirectEncoder` z obsługą API 13.0 dla Pascal / Quadro P400)
3. Wszystkie wygenerowane pliki wideo są w formacie wyłącznie HEVC (H.265), poprawnie zorientowane, z zerowym narzutem pamięci RAM (`0 host copies`).
