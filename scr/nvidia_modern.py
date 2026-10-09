"""Capability probes and FFmpeg command construction for NVIDIA Modern.

This backend deliberately uses CUDA only for decode and input scaling.  The
frames are downloaded before ASS/timing/stack filters, matching the tested
RTX 5070 Ti pipeline while leaving the NVIDIA Legacy path untouched.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path


_CACHE: dict[tuple, tuple[bool, str]] = {}
_CACHE_LOCK = threading.Lock()
_GPU_ARCH_INFO: dict | None = None


def classify_nvidia_architecture(compute_capability) -> tuple[str, str]:
    """Classify by CUDA compute capability; unknown information fails closed."""
    if isinstance(compute_capability, str):
        match = re.search(r"(\d+)\.(\d+)", compute_capability)
        cc = (int(match.group(1)), int(match.group(2))) if match else None
    elif isinstance(compute_capability, (tuple, list)) and len(compute_capability) >= 2:
        try:
            cc = (int(compute_capability[0]), int(compute_capability[1]))
        except (TypeError, ValueError):
            cc = None
    else:
        cc = None
    if cc is None:
        return "LEGACY", "COMPUTE_CAPABILITY_UNKNOWN_SAFE_LEGACY"
    if cc >= (7, 5):
        return "MODERN", "COMPUTE_CAPABILITY_GE_7.5"
    return "LEGACY", "COMPUTE_CAPABILITY_LT_7.5"


def classify_nvidia_gpu(name: str, compute_capability) -> dict:
    """Return a logging/selection record; name is never used to classify."""
    arch_class, reason = classify_nvidia_architecture(compute_capability)
    if compute_capability is None:
        cc_text = "UNKNOWN"
    elif isinstance(compute_capability, (tuple, list)):
        cc_text = f"{compute_capability[0]}.{compute_capability[1]}"
    else:
        match = re.search(r"(\d+)\.(\d+)", str(compute_capability))
        cc_text = f"{match.group(1)}.{match.group(2)}" if match else "UNKNOWN"
    if cc_text == "UNKNOWN":
        arch_class = "LEGACY"
    return {
        "name": name or "UNKNOWN",
        "compute_capability": cc_text,
        "architecture_class": arch_class,
        "reason": reason,
    }


def _detect_nvidia_gpu_info() -> dict:
    """Read compute capability from nvidia-smi, then CUDA Driver API as fallback."""
    smi = shutil.which("nvidia-smi") or "nvidia-smi"
    try:
        proc = subprocess.run(
            [smi, "--query-gpu=name,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                name, separator, cc = line.partition(",")
                if separator and re.search(r"\d+\.\d+", cc):
                    return classify_nvidia_gpu(name.strip(), cc.strip()) | {"source": "nvidia-smi"}
    except (OSError, subprocess.TimeoutExpired):
        pass

    if os.name == "nt":
        try:
            import ctypes
            driver = ctypes.WinDLL("nvcuda.dll")
            driver.cuInit.argtypes = [ctypes.c_uint]
            driver.cuInit.restype = ctypes.c_int
            driver.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
            driver.cuDeviceGetCount.restype = ctypes.c_int
            driver.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
            driver.cuDeviceGet.restype = ctypes.c_int
            driver.cuDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            driver.cuDeviceGetName.restype = ctypes.c_int
            driver.cuDeviceComputeCapability.argtypes = [
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_int,
            ]
            driver.cuDeviceComputeCapability.restype = ctypes.c_int
            if driver.cuInit(0) == 0:
                count = ctypes.c_int()
                if driver.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0:
                    device = ctypes.c_int()
                    major, minor = ctypes.c_int(), ctypes.c_int()
                    if driver.cuDeviceGet(ctypes.byref(device), 0) == 0 and driver.cuDeviceComputeCapability(
                        ctypes.byref(major), ctypes.byref(minor), device.value
                    ) == 0:
                        name_buffer = ctypes.create_string_buffer(256)
                        driver.cuDeviceGetName(name_buffer, len(name_buffer), device.value)
                        name = name_buffer.value.decode("utf-8", errors="replace")
                        return classify_nvidia_gpu(name, (major.value, minor.value)) | {"source": "CUDA Driver API"}
        except (OSError, AttributeError, ValueError):
            pass
    return classify_nvidia_gpu("UNKNOWN", None) | {"source": "unavailable"}


def detect_nvidia_gpu_info(refresh: bool = False) -> dict:
    """Cached architecture record for the default NVIDIA CUDA device."""
    global _GPU_ARCH_INFO
    with _CACHE_LOCK:
        if refresh or _GPU_ARCH_INFO is None:
            _GPU_ARCH_INFO = _detect_nvidia_gpu_info()
        return dict(_GPU_ARCH_INFO)


def _log_nvidia_gpu_info(info: dict) -> None:
    print(f"[export] NVIDIA_GPU_NAME={info.get('name', 'UNKNOWN')}")
    print(f"[export] NVIDIA_COMPUTE_CAPABILITY={info.get('compute_capability', 'UNKNOWN')}")
    print(f"[export] NVIDIA_ARCH_CLASS={info.get('architecture_class', 'LEGACY')}")
    print(f"[export] NVIDIA_MODERN_REASON={info.get('reason', 'UNKNOWN')}; source={info.get('source', 'test')}")


def _cached_probe(key: tuple, command: list[str], timeout: float = 25.0) -> tuple[bool, str]:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        detail = (proc.stderr or proc.stdout or "").strip()
        result = (proc.returncode == 0, detail[-4000:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = (False, str(exc))
    with _CACHE_LOCK:
        _CACHE[key] = result
    return result


def preset_name(preset: str) -> str:
    return {"speed": "p2", "balanced": "p4", "quality": "p6"}.get(
        str(preset).lower(), str(preset)
    )


def _probe_nvidia_modern_preset(ffmpeg_exe: str, input_path: str, preset: str) -> tuple[bool, str]:
    source = Path(input_path)
    try:
        stat = source.stat()
        source_key = (str(source.resolve()).lower(), stat.st_size, stat.st_mtime_ns)
    except OSError:
        source_key = (str(source).lower(), None, None)
    p = preset_name(preset)
    key = ("nvidia-modern", str(Path(ffmpeg_exe).resolve()).lower(), source_key, p)
    command = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", input_path,
        "-vf", "scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12",
        "-frames:v", "1", "-an", "-c:v", "hevc_nvenc", "-preset", p,
        "-f", "null", "NUL",
    ]
    return _cached_probe(key, command)


def probe_nvidia_modern(ffmpeg_exe: str, input_path: str, preset: str = "balanced") -> tuple[bool, str]:
    """Real-source CUDA probe; p4 is mandatory, then verify the selected preset."""
    gpu_info = detect_nvidia_gpu_info()
    _log_nvidia_gpu_info(gpu_info)
    if gpu_info.get("architecture_class") != "MODERN":
        detail = f"Architektura NVIDIA zaklasyfikowana jako LEGACY: {gpu_info.get('reason')}"
        print("[export] NVIDIA_MODERN_PROBE=FAIL")
        print(f"[export] NVIDIA_MODERN_REASON={detail}")
        return False, detail
    requested = preset_name(preset)
    balanced_ok, balanced_detail = _probe_nvidia_modern_preset(ffmpeg_exe, input_path, "p4")
    if not balanced_ok:
        detail = f"Wymagany probe hevc_nvenc p4 nie przeszedł: {balanced_detail}"
        print("[export] NVIDIA_MODERN_PROBE=FAIL")
        print(f"[export] NVIDIA_MODERN_REASON={detail}")
        return False, detail
    if requested == "p4":
        print("[export] NVIDIA_MODERN_PROBE=PASS")
        print("[export] NVIDIA_MODERN_REASON=MODERN_ARCHITECTURE_AND_FFMPEG_P4_PROBE_PASS")
        return True, balanced_detail
    selected_ok, selected_detail = _probe_nvidia_modern_preset(ffmpeg_exe, input_path, requested)
    if not selected_ok:
        detail = f"Probe wybranego hevc_nvenc {requested} nie przeszedł: {selected_detail}"
        print("[export] NVIDIA_MODERN_PROBE=FAIL")
        print(f"[export] NVIDIA_MODERN_REASON={detail}")
        return False, detail
    print("[export] NVIDIA_MODERN_PROBE=PASS")
    print(f"[export] NVIDIA_MODERN_REASON=MODERN_ARCHITECTURE_AND_P4_AND_{requested.upper()}_PROBES_PASS")
    return True, selected_detail


def dual4k_dimensions(layout: str, pad_to_16_9: bool = False) -> tuple[int, int]:
    if pad_to_16_9:
        return 7680, 4320
    return (7680, 2160) if layout == "left_right" else (3840, 4320)


def probe_nvidia_dual4k(
    ffmpeg_exe: str, layout: str, preset: str = "balanced", pad_to_16_9: bool = True
) -> tuple[bool, str]:
    """Actually initialize split-frame NVENC at the requested composite size."""
    width, height = dual4k_dimensions(layout, pad_to_16_9)
    p = preset_name(preset)
    key = ("nvidia-dual4k", str(Path(ffmpeg_exe).resolve()).lower(), width, height, p)
    command = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1",
        "-frames:v", "1", "-an", "-c:v", "hevc_nvenc", "-preset", p,
        "-split_encode_mode", "forced", "-f", "null", "NUL",
    ]
    return _cached_probe(key, command)


def _even(value: float) -> int:
    return max(2, int(math.floor(value / 2.0)) * 2)


def _escape_ass_path(path: str) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def modern_input_size(source_width: int, source_height: int, layout: str, scale: float) -> tuple[int, int]:
    """Match the old post-stack scale caps by moving the same ratio pre-download."""
    stack_width = source_width * (2 if layout == "left_right" else 1)
    stack_height = source_height * (1 if layout == "left_right" else 2)
    ratio = min(float(scale), 3840.0 / max(1, stack_width), 2160.0 / max(1, stack_height))
    return _even(source_width * ratio), _even(source_height * ratio)


def build_command(
    *, ffmpeg_exe: str, video_paths: tuple[str, str], output: str, layout: str,
    input_size: tuple[int, int], scale: float, dual4k: bool, preset: str,
    bitrate_mbps: float, duration: float, delays: tuple[float, float],
    audio_present: tuple[bool, bool], audio_mode: str, ass_paths: tuple[str | None, str | None],
    pad_to_4k: bool | None = None, playback_speed: int = 1, output_fps: float = 30.0,
    pad_to_16_9: bool | None = None, preview_port: int | None = None,
    preview_size: tuple[int, int] = (640, 360),
    preview_fps: float = 5.0,
    orientation_filters: tuple[str, str] = ("", ""),
    clear_output_rotation: bool = True,
) -> tuple[list[str], tuple[int, int]]:
    """Build a single-pass Modern export with fixed output canvas and playback rate."""
    if playback_speed not in (1, 2, 4):
        raise ValueError("Playback speed must be 1, 2, or 4")
    pad_canvas = bool(pad_to_16_9 if pad_to_16_9 is not None else (pad_to_4k if pad_to_4k is not None else True))
    if dual4k:
        if input_size != (3840, 2160):
            raise ValueError("Tryb 4K UHD na kamerę wymaga dwóch wejść 3840×2160.")
        per_input = (3840, 2160)
        stack_size = (7680, 2160) if layout == "left_right" else (3840, 4320)
        output_size = (7680, 4320) if pad_canvas else stack_size
    else:
        per_input = (1920, 1080)
        stack_size = (3840, 1080) if layout == "left_right" else (1920, 2160)
        output_size = (3840, 2160) if pad_canvas else stack_size

    filters = []
    for i in range(2):
        ass = "null"
        if ass_paths[i]:
            ass = f"ass=filename='{_escape_ass_path(ass_paths[i])}'"
        cuda_scale = "scale_cuda=format=nv12" if dual4k else f"scale_cuda={per_input[0]}:{per_input[1]}:format=nv12"
        orientation = orientation_filters[i] or "null"
        # Quarter-turns swap width and height. Fit the upright pixels to the
        # camera slot before ASS so overlays use the normalized canvas.
        if orientation_filters[i] and orientation_filters[i].startswith("transpose="):
            orientation += (
                f",scale={per_input[0]}:{per_input[1]}:force_original_aspect_ratio=decrease:force_divisible_by=2"
                f",pad={per_input[0]}:{per_input[1]}:(ow-iw)/2:(oh-ih)/2:black"
            )
        filters.append(
            f"[{i}:v]{cuda_scale},"
            f"hwdownload,format=nv12,{orientation}[orient_fix{i}];"
            f"[orient_fix{i}]setpts=PTS-STARTPTS,{ass},"
            f"tpad=start_mode=clone:start_duration={delays[i]}:"
            f"stop_mode=clone:stop_duration={duration},trim=duration={duration}[v{i}]"
        )
    stack = "hstack" if layout == "left_right" else "vstack"
    filters.append(f"[v0][v1]{stack}=inputs=2[composite]")
    composite = "[composite]"
    speed_filter = f"setpts=(PTS-STARTPTS)/{playback_speed}," if playback_speed > 1 else "setpts=PTS-STARTPTS,"
    filters.append(f"{composite}{speed_filter}fps={output_fps:g}[stacked_fps]")
    if pad_canvas and output_size != stack_size:
        filters.append(
            f"[stacked_fps]pad={output_size[0]}:{output_size[1]}:(ow-iw)/2:(oh-ih)/2:black[vpad]"
        )
        final_video = "[vpad]"
    else:
        final_video = "[stacked_fps]"
    if preview_port:
        preview_width, preview_height = preview_size
        filters.append(
            f"{final_video}split=2[v][preview_source];"
            f"[preview_source]fps={float(preview_fps):g},scale={preview_width}:{preview_height}:force_original_aspect_ratio=decrease,"
            "format=yuvj420p[preview]"
        )
    else:
        filters.append(f"{final_video}null[v]")

    selected_audio = [
        i for i in range(2) if audio_present[i]
        and audio_mode in (("left", "both") if i == 0 else ("right", "both"))
    ]
    for i in selected_audio:
        filters.append(
            f"[{i}:a]asetpts=PTS-STARTPTS,adelay={delays[i] * 1000}:all=1,"
            f"apad,atrim=duration={duration}[a{i}]"
        )
    if selected_audio:
        filters.append(
            "".join(f"[a{i}]" for i in selected_audio)
            + (f"amix=inputs={len(selected_audio)}:duration=longest" if len(selected_audio) > 1 else "anull")
            + (f",atempo=2,atempo=2" if playback_speed == 4 else ",atempo=2" if playback_speed == 2 else "")
            + f",atrim=duration={duration / playback_speed:g}[a]"
        )

    args = ["-y"]
    for path in video_paths:
        args += ["-noautorotate", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", path]
    args += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if selected_audio:
        args += ["-map", "[a]", "-c:a", "aac"]
    args += ["-fps_mode", "cfr", "-r", f"{output_fps:g}", "-c:v", "hevc_nvenc", "-preset", preset_name(preset)]
    if bitrate_mbps:
        args += ["-b:v", f"{bitrate_mbps:g}M"]
    if dual4k:
        args += ["-split_encode_mode", "forced"]
    if clear_output_rotation:
        args += ["-metadata:s:v:0", "rotate=0"]
    args += ["-t", str(duration / playback_speed), output]
    if preview_port:
        args += [
            "-map", "[preview]", "-an", "-c:v", "mjpeg", "-q:v", "18",
            "-fps_mode", "passthrough", "-f", "fifo", "-queue_size", "2",
            "-drop_pkts_on_overflow", "1", "-fifo_format", "mjpeg",
            "-flush_packets", "1", f"tcp://127.0.0.1:{int(preview_port)}?tcp_nodelay=1",
        ]
    return args, output_size


def command_for_log(ffmpeg_exe: str, args: list[str]) -> str:
    """Windows command line rendered with the same quoting rules as QProcess."""
    return subprocess.list2cmdline([ffmpeg_exe, *args])
