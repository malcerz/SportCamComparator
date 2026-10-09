# SportCamComparator

SportCamComparator plays, synchronizes, and compares two action-camera recordings. It supports side-by-side and top/bottom layouts, GPMF telemetry, audio synchronization, and exports with overlays.

## Features

- Two-video preview with synchronization and playback-speed controls.
- GoPro and DJI telemetry in preview and exported video.
- NVIDIA Modern/Legacy, AMD D3D11VA→AMF, and Intel QSV hardware export paths, with CPU export fallback.
- D3D11 Zero-Copy export with P010, HLG/BT.2020, rotation, and BGRA overlay support.
- Export preview and aspect-ratio/padding controls.

## Requirements

- Windows 10/11 and Python 3.10 or newer.
- FFmpeg `ffmpeg` and `ffprobe` on `PATH` for playback, analysis, and export paths that use the FFmpeg CLI.
- A GPU driver that supports the selected hardware path. NVIDIA, AMD, and Intel have different encoder capabilities; a CPU path is also available.

## Run from source

```powershell
git clone https://github.com/malcerz/SportCamComparator.git
cd SportCamComparator
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python src\main.py
```

If PowerShell blocks environment activation, skip it and invoke `.venv\Scripts\python.exe` directly.

## Build the native D3D11 exporter

The exporter requires the Windows SDK, CMake, a C++17 compiler (Visual Studio C++ Build Tools or GCC/MinGW), Ninja when using GCC, and a shared FFmpeg development package. FFmpeg must provide `include`, `lib`, and optionally `bin` with runtime DLLs compatible with its headers.

Ready-made FFmpeg libraries and local runtime files are not committed. Download a shared FFmpeg development package for Windows and set `FFMPEG_DIR` to its root directory. Alternatively, place it in `third_party/ffmpeg` (that local directory is ignored by Git).

```powershell
$env:FFMPEG_DIR = 'C:\deps\ffmpeg-shared'
Set-ExecutionPolicy -Scope Process Bypass
.\build_gpu_exporter.ps1 -Configuration Release
```

The output is `bin\KomparatorGpuExporter.exe`. Probe available devices and encoders with:

```powershell
& .\bin\KomparatorGpuExporter.exe --probe
```

The NVIDIA Compat script runs the same build and creates an additional executable name, `KomparatorGpuExporterNvidia.exe`:

```powershell
.\build_gpu_exporter_nvidia_compat.ps1 -Configuration Release
```

## Tests

```powershell
python -m compileall -q src tests
python -m pytest -q
```

GPU tests require supported hardware and drivers. Tests for hardware missing from the current system are skipped.

## Assets and engineering notes

UI screenshots are in `assets/`. `RAPORT_*.md` files document fixes, hardware checks, and export-pipeline decisions. Sample videos, generated binaries, logs, and local environments are excluded from the repository.

The Python application uses packages listed in `requirements.txt`; SciPy is optional and improves AutoSync filtering. The native exporter uses an FFmpeg shared development package, NVIDIA NVENC and Intel oneVPL headers in `native/third_party`, the Windows SDK, and Direct3D 11.

If this program is useful, you can buy me a coffee: [buycoffee.to/malcerz](https://buycoffee.to/malcerz).
