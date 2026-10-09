# Video Comparator

Video Comparator is an advanced tool for playing, synchronizing, and comparing two video files (for example, from sports cameras such as GoPro), with a GPMF telemetry overlay. It uses hardware GPU acceleration (NVENC/QSV/AMF) to ensure smooth playback of 4K HEVC videos with a zero-copy pipeline.

## Screenshots

[Left/Right view](https://github.com/malcerz/Komparator/blob/main/assets/skrin1.jpg)  
[Top/Bottom view](https://github.com/malcerz/Komparator/blob/main/assets/skrin2.jpg)

## Main Features

- **Side-by-side and top/bottom preview**: Smooth switching between view layouts.
- **Automatic audio synchronization (AutoSync)**: Precise alignment based on audio energy envelope correlation, with automatic wind-noise filtering above 500 Hz.
- **Telemetry reading (GPMF)**: Displays a telemetry overlay with camera parameters such as date/time, ISO, exposure time, and more, with automatic conversion to the user's system time zone.
- **Overlay toggle**: Lets you disable parameter rendering both in live preview and during export.
- **Hardware acceleration**: UI rendering via Qt/OpenGL/Direct3D with full support for hardware-offloaded video decoding (H.264/H.265).
- **Stable synchronization (Master-Slave)**: A one-way timing sync mechanism (Video 1 controls Video 2) that eliminates feedback loops and helps prevent freezes or stuttering.
- **Informative FFmpeg export**: Exports the synchronized view to disk, with optional burned-in subtitles/overlays. Progress information, including frames, FPS, and estimated time remaining (ETA), is shown directly on the Export button.
- **Automatic localization (PL/EN)**: Automatically adjusts the interface language based on the operating system language.

## System Requirements

- Operating system: Windows 10/11
- Graphics card with hardware H.265 decoding/encoding support (NVIDIA, Intel, or AMD)
- Python 3.10+
- **FFmpeg**: `ffmpeg` and `ffprobe` must be installed and available in the system `PATH`

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd Komparator
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Running

To start the application in development mode, run:

```bash
python src/main.py
```

## Building the `.exe`

For easier distribution, you can compile the application into a standalone binary using PyInstaller. A precompiled version ready to run is also available in Releases.

To build the application on Windows, run:

```bash
pyinstaller main.spec
```

The finished `main.exe` file will appear in the `dist/` folder.

## Technologies and Dependencies

- [PySide6](https://pypi.org/project/PySide6/) (GUI and the QtMultimedia engine)
- [numpy](https://pypi.org/project/numpy/) / [scipy](https://pypi.org/project/scipy/) (audio analysis and offset detection)
- FFmpeg (for exporting merged streams)

If you like this program, you can buy me a coffee: [buycoffee.to/malcerz](https://buycoffee.to/malcerz)
