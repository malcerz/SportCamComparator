"""Automatic capability detection, benchmarking, and caching for export backends.

Determines the optimal export backend (D3D11 Zero-Copy vs Legacy FFmpeg vs CPU)
based on real hardware capability, short synthetic benchmarks, and persistent caching.
"""
import json
import os
import subprocess
import time
from pathlib import Path
import video_encoder


class BackendSelector:
    @staticmethod
    def _get_cache_file() -> Path:
        """Return writable cache path — works in dev, Nuitka standalone, and MSIX install.

        MSIX install directory is READ-ONLY. QStandardPaths.AppLocalDataLocation
        resolves to %LOCALAPPDATA%\Comparator which is always writable.
        Falls back to build/ in source mode if Qt is not available.
        """
        try:
            from PySide6.QtCore import QStandardPaths, QCoreApplication
            # Ensure app name is set (safe to call repeatedly)
            if not QCoreApplication.applicationName():
                QCoreApplication.setApplicationName("Comparator")
            writable = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
            if writable:
                return Path(writable) / "cache" / "backend_benchmark_cache.json"
        except Exception:
            pass
        # Dev fallback: write next to project build/ directory
        return video_encoder.get_app_root() / "build" / "backend_benchmark_cache.json"


    @classmethod
    def _load_cache(cls) -> dict:
        try:
            f = cls._get_cache_file()
            if f.is_file():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @classmethod
    def _save_cache(cls, cache: dict):
        try:
            f = cls._get_cache_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except Exception:
            pass


    @classmethod
    def get_cache_key(cls, hw: str, width: int, height: int, codec: str = "hevc") -> str:
        # Categorize resolution class
        w, h = width, height
        if w >= 3840 and h >= 2160:
            res_class = "3840x2160"
        elif w >= 3840 and h >= 1080:
            res_class = "3840x1080"
        elif w <= 1920 and h >= 2160:
            res_class = "1920x2160"
        else:
            res_class = f"{w}x{h}"
        return f"{hw.upper()}_{codec.lower()}_{res_class}"

    @classmethod
    def benchmark_d3d11(cls, encoder_short: str, preset: str, width: int, height: int) -> float:
        """Measure D3D11 exporter FPS on synthetic frames."""
        helper, _ = video_encoder.resolve_export_helper("d3d11", encoder_short)
        if not helper:
            return 0.0
        # Probe already executes initialization and timing
        t0 = time.perf_counter()
        ok, _, data = video_encoder.probe_gpu_exporter(encoder_short, preset, width, height)
        dt = time.perf_counter() - t0
        if not ok:
            return 0.0
        # If probe succeeded with zero-copy, estimate base rate from probe
        return 100.0 / max(0.01, dt)

    @classmethod
    def benchmark_legacy(cls, hw: str, encoder_name: str, width: int, height: int, preset: str = "balanced") -> float:
        """Measure Legacy FFmpeg FPS on 30 synthetic frames at the selected preset."""
        ffmpeg_exe = video_encoder.resolve_legacy_ffmpeg(hw)
        cmd = [
            ffmpeg_exe, "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=30",
            "-frames:v", "30",
            "-c:v", encoder_name,
        ]
        if "nvenc" in encoder_name:
            nv_preset = {"speed": "p2", "balanced": "p4", "quality": "p6"}.get(str(preset).lower(), "p4")
            cmd += ["-preset", nv_preset]
        cmd += ["-f", "null", "-"]
        t0 = time.perf_counter()
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=8)
            dt = time.perf_counter() - t0
            if res.returncode == 0 and dt > 0:
                return 30.0 / dt
        except Exception:
            pass
        return 0.0

    @classmethod
    def select_backend(
        cls,
        hw: str,
        width: int,
        height: int,
        preset: str = "balanced",
        codec: str = "hevc",
        force_benchmark: bool = False,
    ) -> tuple[str, str]:
        """Automatically select the best backend.

        Returns:
            (mode, selected_backend_name)
            mode is 'd3d11' or 'legacy'
            selected_backend_name is e.g. 'NVIDIA_D3D11', 'INTEL_QSV_D3D11', 'AMD_AMF_D3D11', 'NVIDIA_LEGACY', 'CPU_X265'
        """
        # Manual override via environment variable if requested
        env_backend = os.getenv("COMPARATOR_BACKEND", "").lower()
        if env_backend == "d3d11":
            return "d3d11", f"{hw.upper().replace(' ', '_')}_D3D11"
        elif env_backend in ("legacy", "ffmpeg"):
            return "legacy", f"{hw.upper().replace(' ', '_')}_LEGACY"

        hw_upper = hw.upper()
        if hw_upper == "CPU":
            return "legacy", "CPU_X265"

        encoder_short = {
            "NVIDIA": "nvenc",
            "AMD AMF": "amf",
            "INTEL QSV": "qsv",
        }.get(hw_upper, "cpu")

        legacy_encoder = {
            "NVIDIA": "hevc_nvenc",
            "AMD AMF": "hevc_amf",
            "INTEL QSV": "hevc_qsv",
        }.get(hw_upper, "libx265")

        ffmpeg_exe = video_encoder.resolve_legacy_ffmpeg(hw)

        # 1. Probe D3D11
        d3d11_ok, _, _ = video_encoder.probe_gpu_exporter(encoder_short, preset, width, height, codec)

        # 2. Probe Legacy
        legacy_ok = video_encoder.probe_legacy_encoder(legacy_encoder, ffmpeg_exe)

        print(f"[backend] Capabilities for {hw}: D3D11={d3d11_ok}, Legacy={legacy_ok}")

        if d3d11_ok and not legacy_ok:
            return "d3d11", f"{hw_upper.replace(' ', '_')}_D3D11"

        if legacy_ok and not d3d11_ok:
            return "legacy", f"{hw_upper.replace(' ', '_')}_LEGACY"

        if not d3d11_ok and not legacy_ok:
            print(f"[backend] Both hardware backends failed for {hw}. Falling back to CPU.")
            return "legacy", "CPU_X265"

        # Both work! Check cache
        cache = cls._load_cache()
        cache_key = cls.get_cache_key(hw, width, height, codec)

        if not force_benchmark and cache_key in cache:
            cached_winner = cache[cache_key].get("winner")
            if cached_winner in ("d3d11", "legacy"):
                print(f"[backend] Using cached winner for {cache_key}: {cached_winner.upper()}")
                mode = cached_winner
                bname = f"{hw_upper.replace(' ', '_')}_{mode.upper()}"
                return mode, bname

        # Run short benchmark
        print(f"[backend] Running short benchmark for {hw} ({width}x{height})...")
        d3d_fps = cls.benchmark_d3d11(encoder_short, preset, width, height)
        leg_fps = cls.benchmark_legacy(hw, legacy_encoder, width, height, preset)

        print(f"[backend] Benchmark results: D3D11={d3d_fps:.1f} fps, Legacy={leg_fps:.1f} fps")

        # Threshold: if within 5%, prefer D3D11 Zero-Copy (zero CPU/RAM copy overhead)
        if leg_fps > 0 and (leg_fps - d3d_fps) / leg_fps > 0.05:
            winner = "legacy"
        else:
            winner = "d3d11"

        cache[cache_key] = {
            "hw": hw,
            "width": width,
            "height": height,
            "d3d_fps": d3d_fps,
            "legacy_fps": leg_fps,
            "winner": winner,
            "timestamp": time.time(),
        }
        cls._save_cache(cache)
        print(f"[backend] Winner selected: {winner.upper()}")

        return winner, f"{hw_upper.replace(' ', '_')}_{winner.upper()}"
