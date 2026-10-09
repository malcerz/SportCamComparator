"""Benchmark the production NVIDIA Modern decode/scale/download/stack/NVENC path."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import nvidia_modern
import video_encoder


def probe_size(ffprobe: str, path: str) -> tuple[int, int, float]:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,r_frame_rate", "-of", "json", path],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"ffprobe failed: {path}")
    stream = json.loads(proc.stdout)["streams"][0]
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1"
    numerator, denominator = (int(part) for part in rate.split("/", 1))
    fps = numerator / denominator if denominator else 30.0
    return int(stream["width"]), int(stream["height"]), fps


def reference_command(ffmpeg: str, video1: str, video2: str, dual4k: bool = False) -> list[str]:
    """Hand-written reference argv; intentionally independent of production builder."""
    if dual4k:
        graph = (
            "[0:v]scale_cuda=format=nv12,hwdownload,format=nv12[v0];"
            "[1:v]scale_cuda=format=nv12,hwdownload,format=nv12[v1];"
            "[v0][v1]vstack=inputs=2:shortest=1[out]"
        )
    else:
        graph = (
            "[0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12[v0];"
            "[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12[v1];"
            "[v0][v1]vstack=inputs=2:shortest=1[out]"
        )
    argv = [
        ffmpeg, "-hide_banner", "-benchmark", "-stats",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", video1,
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", video2,
        "-filter_complex", graph, "-map", "[out]", "-an",
        "-fps_mode", "passthrough", "-c:v", "hevc_nvenc", "-preset", "p4",
        "-b:v", "10M", "-f", "null", "NUL",
    ]
    if dual4k:
        argv[-3:-3] = ["-split_encode_mode", "forced"]
    return argv


def _stats(stderr: str) -> dict:
    lines = re.split(r"[\r\n]+", stderr)
    frame, fps, speed = None, None, None
    for line in lines:
        match = re.search(r"frame=\s*(\d+).*?fps=\s*([\d.]+).*?speed=\s*([\d.]+)x", line)
        if match:
            frame, fps, speed = int(match.group(1)), float(match.group(2)), float(match.group(3))
    result = {"ffmpeg_reported_frames": frame, "ffmpeg_reported_fps": fps, "ffmpeg_reported_speed": speed}
    elapsed = re.search(r"\brtime=([\d.]+)s", stderr)
    if elapsed:
        result["ffmpeg_elapsed_seconds"] = float(elapsed.group(1))
    rss = re.search(r"maxrss=(\d+)KiB", stderr)
    if rss:
        result["peak_rss_mib"] = round(int(rss.group(1)) / 1024.0, 1)
    progress_elapsed = None
    for line in lines:
        match = re.search(r"elapsed=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
        if match:
            progress_elapsed = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    if progress_elapsed is not None:
        result["ffmpeg_reported_elapsed_seconds"] = progress_elapsed
    return result


def _console_popen(argv: list[str], timeout: int) -> tuple[int, str, float]:
    """Drain stderr continuously while echoing it, so the pipe cannot throttle FFmpeg."""
    started = time.perf_counter()
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            bufsize=1, universal_newlines=True)
    chunks = []
    def drain():
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read(4096), ""):
            chunks.append(chunk)
            sys.stderr.write(chunk)
            sys.stderr.flush()
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    reader.join()
    return code, "".join(chunks), time.perf_counter() - started


def run_command(argv: list[str], stderr_mode: str, stderr_file: str | None, timeout: int,
                stop_after: float | None = None) -> tuple[float, str]:
    print(f"FFMPEG_COMMAND={subprocess.list2cmdline(argv)}", flush=True)
    print(f"CWD={Path.cwd()}", flush=True)
    print(f"FFMPEG_EXE={argv[0]}", flush=True)
    print(f"PATH_FFMPEG={shutil.which('ffmpeg.exe') or shutil.which('ffmpeg') or '<not-on-PATH>'}", flush=True)
    print(f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')}", flush=True)
    print(f"PYTHON_EXE={sys.executable}", flush=True)
    print(f"PARENT_PID={os.getpid()}", flush=True)
    print("SUBPROCESS_CREATIONFLAGS=0 (subprocess defaults)", flush=True)
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
            kernel.GetPriorityClass.restype = ctypes.c_uint
            kernel.GetProcessAffinityMask.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t),
            ]
            kernel.GetProcessAffinityMask.restype = ctypes.c_int
            handle = kernel.GetCurrentProcess()
            priority = kernel.GetPriorityClass(handle)
            process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
            affinity_ok = kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask))
            print(f"PROCESS_PRIORITY_CLASS=0x{priority:X}", flush=True)
            print(f"PROCESS_AFFINITY_MASK=0x{process_mask.value:X}" if affinity_ok else "PROCESS_AFFINITY_MASK=UNAVAILABLE", flush=True)
        except (AttributeError, OSError, ValueError):
            print("PROCESS_PRIORITY_CLASS/PROCESS_AFFINITY_MASK=UNAVAILABLE", flush=True)
    started = time.perf_counter()
    if stop_after is not None:
        started = time.perf_counter()
        stderr_path = Path(stderr_file or "benchmark_ffmpeg_stderr.log") if stderr_mode == "file" else None
        if stderr_path:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr_handle, text=True)
            reader = None
        else:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            chunks = []
            def drain_stop():
                assert proc.stderr is not None
                for chunk in iter(lambda: proc.stderr.read(4096), ""):
                    chunks.append(chunk)
                    if stderr_mode == "console":
                        sys.stderr.write(chunk)
                        sys.stderr.flush()
            reader = threading.Thread(target=drain_stop, daemon=True)
            reader.start()
        try:
            proc.wait(timeout=stop_after)
        except subprocess.TimeoutExpired:
            if proc.stdin:
                proc.stdin.write("q\n")
                proc.stdin.flush()
                proc.stdin.close()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
        if reader:
            reader.join()
            stderr = "".join(chunks)
        elif stderr_path:
            stderr_handle.close()
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
            print(f"STDERR_FILE={stderr_path}")
        else:
            stderr = ""
        elapsed, code = time.perf_counter() - started, proc.returncode
    elif stderr_mode == "console":
        code, stderr, elapsed = _console_popen(argv, timeout)
    elif stderr_mode == "file":
        destination = Path(stderr_file or "benchmark_ffmpeg_stderr.log")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", errors="replace") as handle:
            proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=handle, timeout=timeout)
        elapsed, stderr = time.perf_counter() - started, destination.read_text(encoding="utf-8", errors="replace")
        print(f"STDERR_FILE={destination}")
        code = proc.returncode
    else:
        # Match the earlier harness exactly: capture both stdout and stderr,
        # with subprocess.run/communicate draining the pipes while FFmpeg runs.
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        elapsed, stderr, code = time.perf_counter() - started, proc.stderr, proc.returncode
    if code:
        raise RuntimeError(f"FFmpeg failed ({code}):\n{stderr[-6000:]}")
    return elapsed, stderr


def add_limit(argv: list[str], frames: int | None, duration: float | None) -> list[str]:
    if frames is None and duration is None:
        return list(argv)
    result = list(argv[:-3])
    if frames is not None:
        result += ["-frames:v", str(frames)]
    if duration is not None:
        result += ["-t", str(duration)]
    result += argv[-3:]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video1")
    parser.add_argument("video2")
    parser.add_argument("--layout", choices=("top_bottom", "left_right"), default="top_bottom")
    parser.add_argument("--dual4k", action="store_true")
    parser.add_argument("--preset", choices=("speed", "balanced", "quality"), default="balanced")
    parser.add_argument("--ffmpeg-exe", help="Override the selected FFmpeg binary (diagnostics only)")
    parser.add_argument("--warmup-frames", type=int, default=300)
    parser.add_argument("--frames", type=int, help="Measured frame limit; default 3000 for production graph")
    parser.add_argument("--duration", type=float, help="Output duration limit in seconds")
    parser.add_argument("--reference-command", action="store_true", help="Run the hand-written reference graph, independent of production builder")
    parser.add_argument("--stderr-mode", choices=("pipe", "file", "console"), default="pipe")
    parser.add_argument("--stderr-file")
    parser.add_argument("--stop-after", type=float, help="Gracefully send q after this many wall-clock seconds; leaves argv unchanged")
    parser.add_argument("--json", dest="json_path")
    opts = parser.parse_args()
    if opts.frames is not None and opts.frames < 1:
        parser.error("--frames must be positive")
    if opts.duration is not None and opts.duration <= 0:
        parser.error("--duration must be positive")
    if opts.stop_after is not None and opts.stop_after <= 0:
        parser.error("--stop-after must be positive")
    if opts.frames is not None and opts.duration is not None:
        parser.error("choose either --frames or --duration")
    if opts.warmup_frames < 1:
        parser.error("--warmup-frames must be positive")

    ffmpeg = opts.ffmpeg_exe or video_encoder.resolve_legacy_ffmpeg("NVIDIA")
    ffprobe = video_encoder.resolve_legacy_ffprobe("NVIDIA")
    probe1 = probe_size(ffprobe, opts.video1)
    probe2 = probe_size(ffprobe, opts.video2)
    size1, source_fps = probe1[:2], probe1[2]
    size2 = probe2[:2]
    if size1 != size2:
        parser.error(f"Input dimensions differ: {size1} and {size2}")
    if not opts.reference_command:
        modern_ok, detail = nvidia_modern.probe_nvidia_modern(ffmpeg, opts.video1, opts.preset)
        if not modern_ok:
            raise SystemExit(f"NVIDIA_MODERN_PROBE=FAIL: {detail}")
    if opts.dual4k and not opts.reference_command:
        if size1 != (3840, 2160):
            parser.error("--dual4k requires two 3840x2160 sources")
        dual_ok, detail = nvidia_modern.probe_nvidia_dual4k(ffmpeg, opts.layout, opts.preset)
        if not dual_ok:
            raise SystemExit(f"NVIDIA_DUAL4K_PROBE=FAIL: {detail}")

    if opts.reference_command:
        if size1 != (3840, 2160):
            parser.error("--reference-command requires two 3840x2160 sources")
        command = add_limit(reference_command(ffmpeg, opts.video1, opts.video2, opts.dual4k), opts.frames, opts.duration)
        output_size = (3840, 4320) if opts.dual4k else (1920, 2160)
        print(f"BENCHMARK_GRAPH=HAND_WRITTEN_REFERENCE{'_DUAL4K' if opts.dual4k else ''}")
        elapsed, ffmpeg_log = run_command(command, opts.stderr_mode, opts.stderr_file, 600, opts.stop_after)
        result = {
            "backend": "NVIDIA_MODERN_REFERENCE_COMMAND", "input_order": [opts.video1, opts.video2],
            "output_size": list(output_size), "preset": "p4", "split_encode_mode": "forced" if opts.dual4k else "disabled",
            "python_wallclock_seconds": round(elapsed, 3),
            "python_wallclock_fps": round((_stats(ffmpeg_log).get("ffmpeg_reported_frames") or 0) / elapsed, 2),
            "python_wallclock_elapsed_seconds": round(elapsed, 3),
            "python_return_code": 0,
            **_stats(ffmpeg_log),
        }
        print(json.dumps(result, indent=2))
        if opts.json_path:
            Path(opts.json_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    if opts.frames is None:
        opts.frames = 3000
    if opts.frames < 3000:
        parser.error("production benchmark --frames must be at least 3000")
    base_command, output_size = nvidia_modern.build_command(
        ffmpeg_exe=ffmpeg, video_paths=(opts.video1, opts.video2), output="NUL",
        layout=opts.layout, input_size=size1, scale=1.0, dual4k=opts.dual4k,
        preset=opts.preset, bitrate_mbps=10.0, duration=3600.0, delays=(0.0, 0.0),
        audio_present=(False, False), audio_mode="mute", ass_paths=(None, None),
        pad_to_4k=False,
    )
    preset = nvidia_modern.preset_name(opts.preset)
    split_mode = "forced" if opts.dual4k else "disabled"
    print(f"WARMUP_FRAMES={opts.warmup_frames}")
    print(f"MEASURED_FRAMES={opts.frames}")
    print(f"OUTPUT_SIZE={output_size[0]}x{output_size[1]}")
    print(f"PRESET={preset}")
    print(f"SPLIT_ENCODE_MODE={split_mode}")
    print("PASS=warmup")
    warmup_command = base_command[:-3] + ["-frames:v", str(opts.warmup_frames), "-benchmark", "-stats", "-f", "null", "NUL"]
    warmup_elapsed, warmup_log = run_command([ffmpeg, *warmup_command], opts.stderr_mode, opts.stderr_file, 240)
    print(f"WARMUP_ELAPSED_SECONDS={warmup_elapsed:.3f}")
    print("PASS=measured")
    measured_command = base_command[:-3] + ["-frames:v", str(opts.frames), "-benchmark", "-stats", "-f", "null", "NUL"]
    elapsed, measured_log = run_command([ffmpeg, *measured_command], opts.stderr_mode, opts.stderr_file, 600)
    result = {
        "backend": "NVIDIA_MODERN_FFMPEG",
        "layout": opts.layout,
        "dual4k": opts.dual4k,
        "split_encode_mode": split_mode,
        "output_size": list(output_size),
        "preset": preset,
        "warmup_frames": opts.warmup_frames,
        "warmup_elapsed_seconds": round(warmup_elapsed, 3),
        "measured_frames": opts.frames,
        "elapsed_measured_seconds": round(elapsed, 3),
        "average_fps": round(opts.frames / elapsed, 2),
        "python_wallclock_fps": round(opts.frames / elapsed, 2),
        "speed": round((opts.frames / elapsed) / source_fps, 3),
        "source_fps": round(source_fps, 3),
    }
    result.update(_stats(measured_log))
    print(json.dumps(result, indent=2))
    if opts.json_path:
        Path(opts.json_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
