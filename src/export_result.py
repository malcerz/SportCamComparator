"""Strict classification and FFprobe validation for completed FFmpeg exports."""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path


def is_preview_only_failure(log_text: str, *, cancelled: bool = False) -> bool:
    """Recognize only a failed secondary FIFO preview after primary progress ended."""
    if cancelled:
        return False
    lines = str(log_text or "").splitlines()
    preview_failed = any(
        ("out#1/fifo" in line.lower() or "vost#1:" in line.lower())
        and any(word in line.lower() for word in ("error", "failed", "terminating thread"))
        for line in lines
    )
    main_failed = any(
        ("out#0/" in line.lower() or "vost#0:" in line.lower())
        and any(word in line.lower() for word in ("error", "failed", "terminating thread"))
        for line in lines
    )
    main_failed = main_failed or any(
        marker in str(log_text or "").lower()
        for marker in ("error while opening encoder", "error initializing output stream",
                       "failed to open encoder", "no encoder found")
    )
    ended = bool(re.search(r"(?:^|\n)progress=end(?:\r?\n|$)", str(log_text or "")))
    final_frame = re.findall(r"(?:^|\n)frame=\s*(\d+)", str(log_text or ""))
    return preview_failed and not main_failed and ended and bool(final_frame) and int(final_frame[-1]) > 0


def validate_completed_mp4(
    ffprobe: str,
    output: str | Path,
    expected_size: tuple[int, int] | None,
    expected_duration: float | None,
    *,
    timeout: float = 15,
) -> dict:
    """Validate MP4 parsing, HEVC stream geometry, duration and frame count when present."""
    path = Path(output)
    if not path.is_file() or path.stat().st_size < 1024:
        raise ValueError("Brak poprawnego pliku MP4.")
    proc = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height,nb_frames,avg_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode:
        raise ValueError("FFprobe nie zaakceptował pliku MP4.")
    info = json.loads(proc.stdout)
    video = next((item for item in info.get("streams", []) if item.get("codec_type") == "video"), None)
    if not video or video.get("codec_name") not in ("hevc", "h265"):
        raise ValueError("Brak poprawnego strumienia HEVC w MP4.")
    actual_size = int(video.get("width", 0)), int(video.get("height", 0))
    if min(actual_size) <= 0 or (expected_size and actual_size != tuple(map(int, expected_size))):
        raise ValueError(f"Nieoczekiwana rozdzielczość strumienia HEVC: {actual_size}.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise ValueError("Kontener MP4 nie ma poprawnego czasu trwania.")
    if expected_duration and expected_duration > 0:
        tolerance = max(0.5, expected_duration * 0.005)
        if abs(duration - expected_duration) > tolerance:
            raise ValueError(
                f"Niekompletny czas eksportu: {duration:.3f}s z oczekiwanych {expected_duration:.3f}s."
            )
    frames = video.get("nb_frames")
    frame_rate = video.get("avg_frame_rate")
    if frames and expected_duration and expected_duration > 0:
        try:
            actual_frames = int(frames)
            fps = float(Fraction(frame_rate))
            expected_frames = round(expected_duration * fps)
            if actual_frames <= 0 or abs(actual_frames - expected_frames) > 2:
                raise ValueError(
                    f"Niekompletna liczba klatek HEVC: {actual_frames} z oczekiwanych {expected_frames}."
                )
        except (ValueError, ZeroDivisionError):
            if frames and str(frames).isdigit():
                raise
    return {"width": actual_size[0], "height": actual_size[1], "duration": duration,
            "codec_name": video["codec_name"], "nb_frames": int(frames) if str(frames or "").isdigit() else None}
