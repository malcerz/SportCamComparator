"""Capability detection, helper resolution, and smoke probes for video encoders."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MAX_OUTPUT_SIZE = (3840, 2160)
FALLBACK_SIZES = ((2560, 1440), (1920, 1080), (1280, 720))

_PROBE_CACHE: dict[tuple, tuple[bool, str, dict]] = {}
_LEGACY_PROBE_CACHE: dict[tuple, bool] = {}
_SIZE_PROBE_CACHE: dict[tuple, tuple[bool, str]] = {}


def get_app_root() -> Path:
    """Return absolute application root path, independent of current working directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_export_helper(backend: str, encoder: str) -> tuple[Path | None, str | None]:
    """Resolve the appropriate GPU export helper binary for a given backend and encoder.

    Returns:
        (helper_path, None) if found.
        (None, None) if backend/encoder does not use GPU helper (e.g. CPU or Legacy).
        (None, error_message) if helper was expected but missing.
    """
    b = str(backend).lower()
    e = str(encoder).lower()

    # CPU or Legacy never require GPU helper
    if b in ("legacy", "cpu") or e in ("cpu", "libx265", "none"):
        return None, None

    app_root = get_app_root()
    bin_dir = app_root / "bin"

    # For NVIDIA, check for isolated compat helper first, then common helper
    if e in ("nvidia", "nvenc", "hevc_nvenc"):
        nv_helper = bin_dir / "KomparatorGpuExporterNvidia.exe"
        if nv_helper.is_file():
            return nv_helper, None
        common_helper = bin_dir / "KomparatorGpuExporter.exe"
        if common_helper.is_file():
            return common_helper, None
        err = (
            f"Nie znaleziono eksportera GPU.\n"
            f"Backend: NVIDIA NVENC\n"
            f"Szukany helper:\n{common_helper}\n"
            f"Uruchom:\n.\\build_gpu_exporter.ps1 -Clean"
        )
        return None, err

    # For AMD AMF, Intel QSV, or auto
    target_helper = bin_dir / "KomparatorGpuExporter.exe"
    if target_helper.is_file():
        return target_helper, None

    err = (
        f"Nie znaleziono eksportera GPU.\n"
        f"Backend: {encoder}\n"
        f"Szukany helper:\n{target_helper}\n"
        f"Uruchom:\n.\\build_gpu_exporter.ps1 -Clean"
    )
    return None, err


def get_gpu_exporter_exe(encoder: str = "auto") -> str | None:
    """Backwards-compatible helper returning string path or None."""
    path, _ = resolve_export_helper("d3d11", encoder)
    return str(path) if path else None


def resolve_legacy_ffmpeg(hw: str = "CPU") -> str:
    """Resolve FFmpeg binary for Legacy export.

    For NVIDIA, prioritize vendor-isolated runtime/nvidia/ffmpeg/ if available.
    Otherwise use bin/ffmpeg.exe or system PATH.
    """
    app_root = get_app_root()
    h = str(hw).upper()

    if "NVIDIA" in h or "NVENC" in h:
        nv_candidates = [
            app_root / "runtime" / "nvidia" / "ffmpeg" / "bin" / "ffmpeg.exe",
            app_root / "runtime" / "nvidia" / "ffmpeg" / "ffmpeg.exe",
        ]
        for cand in nv_candidates:
            if cand.is_file():
                return str(cand)

    # Common bin/ffmpeg.exe
    common_bin = app_root / "bin" / "ffmpeg.exe"
    if common_bin.is_file():
        return str(common_bin)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return "ffmpeg"


def resolve_legacy_ffprobe(hw: str = "CPU") -> str:
    """Resolve FFprobe binary for Legacy export."""
    app_root = get_app_root()
    h = str(hw).upper()

    if "NVIDIA" in h or "NVENC" in h:
        nv_candidates = [
            app_root / "runtime" / "nvidia" / "ffmpeg" / "bin" / "ffprobe.exe",
            app_root / "runtime" / "nvidia" / "ffmpeg" / "ffprobe.exe",
        ]
        for cand in nv_candidates:
            if cand.is_file():
                return str(cand)

    common_bin = app_root / "bin" / "ffprobe.exe"
    if common_bin.is_file():
        return str(common_bin)

    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe

    return "ffprobe"


def probe_gpu_exporter(
    encoder: str = "auto",
    preset: str = "balanced",
    width: int = 3840,
    height: int = 2160,
    codec: str = "hevc",
) -> tuple[bool, str, dict]:
    """Test if GPU exporter is functional via --probe with capability detection."""
    cache_key = (encoder.lower(), preset.lower(), width, height, codec.lower())
    if cache_key in _PROBE_CACHE:
        return _PROBE_CACHE[cache_key]

    helper_path, helper_err = resolve_export_helper("d3d11", encoder)
    if not helper_path:
        res = (False, helper_err or "Brak pliku eksportera GPU", {"reason": "HELPER_NOT_FOUND"})
        _PROBE_CACHE[cache_key] = res
        return res

    cmd = [
        str(helper_path),
        "--probe",
        "--encoder", str(encoder),
        "--preset", str(preset),
        "--width", str(width),
        "--height", str(height),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        # Parse JSON from stdout or stderr
        parsed_data = {}
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed_data = json.loads(line)
                    break
                except Exception:
                    pass

        if proc.returncode == 0 and parsed_data.get("status") == "ok":
            msg = f"D3D11 GPU Exporter gotowy ({parsed_data.get('encoder', encoder)})"
            res = (True, msg, parsed_data)
        else:
            reason = parsed_data.get("reason", "PROBE_FAILED")
            detail = parsed_data.get("message") or stderr or stdout or "Nieznany błąd probe"
            msg = f"{reason}: {detail}"
            res = (False, msg, parsed_data or {"reason": reason, "message": detail})

    except Exception as exc:
        res = (False, f"Błąd uruchomienia probe: {exc}", {"reason": "PROBE_EXECUTION_ERROR"})

    _PROBE_CACHE[cache_key] = res
    return res


def probe_legacy_encoder(encoder: str, ffmpeg_exe: str = "ffmpeg", timeout: float = 3.0) -> bool:
    """Test if a given FFmpeg encoder can successfully initialize in Legacy FFmpeg."""
    cache_key = (encoder.lower(), ffmpeg_exe)
    if cache_key in _LEGACY_PROBE_CACHE:
        return _LEGACY_PROBE_CACHE[cache_key]

    cmd = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=1",
        "-frames:v", "1", "-an", "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        ok = (proc.returncode == 0)
    except (OSError, subprocess.TimeoutExpired):
        ok = False

    _LEGACY_PROBE_CACHE[cache_key] = ok
    return ok


def gpu_export_gaps() -> list[str]:
    """Describe missing components for a zero-copy D3D11 two-video export."""
    ok, msg, _ = probe_gpu_exporter()
    if ok:
        return []

    try:
        ffmpeg_exe = resolve_legacy_ffmpeg()
        result = subprocess.run([ffmpeg_exe, "-hide_banner", "-filters"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Nie można odczytać możliwości FFmpeg: {exc}"]

    output = result.stdout + result.stderr
    required = {
        "scale_d3d11": "sprzętowe skalowanie D3D11",
        "overlay_d3d11": "sprzętowe łączenie klipów/warstw D3D11",
    }
    missing = [label for name, label in required.items() if name not in output]
    if missing:
        missing.insert(0, f"Natywny eksporter GPU: {msg}")
    return missing


def probe_encoder_limit(encoder: str, ffmpeg_exe: str = "ffmpeg", timeout: float = 2.0) -> tuple[int, int] | None:
    """Return the largest tested (width, height), or None if unusable."""
    for width, height in (MAX_OUTPUT_SIZE, *FALLBACK_SIZES):
        command = [
            ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1",
            "-frames:v", "1", "-an", "-c:v", encoder, "-f", "null", "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return width, height
    return None


def probe_encoder_size(encoder: str, width: int, height: int, ffmpeg_exe: str = "ffmpeg", timeout: float = 5.0) -> tuple[bool, str]:
    """Quickly verify one target frame at the exact output dimensions."""
    key = (encoder.lower(), int(width), int(height), ffmpeg_exe)
    if key in _SIZE_PROBE_CACHE:
        return _SIZE_PROBE_CACHE[key]
    command = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1",
        "-frames:v", "1", "-an", "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        ok = result.returncode == 0
        detail = "PASS" if ok else (result.stderr.strip() or f"exit={result.returncode}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, detail = False, str(exc)
    _SIZE_PROBE_CACHE[key] = (ok, detail)
    return ok, detail
