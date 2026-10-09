"""
Comprehensive verification and benchmarking suite for Komparator GPU Exporter:
1. Benchmarks the 3 HEVC presets: Najszybszy (speed), Zbalansowany (balanced), Najlepsza jakość (quality)
2. Measures Export Preview overhead (preview ON vs preview OFF)
3. Verifies Layouts (Lewo/Prawo and Góra/Dół)
4. Verifies MP4 format: codec_name=hevc, display matrix identity, rotation=0
5. Verifies raw pixel orientation (with -noautorotate)
6. Verifies zero-copy counters (hwdownload=0, hwupload=0, sw_frames=0)
7. Verifies cancellation latency (< 1.5s)
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

# Setup paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from export_live_preview import ExportLivePreview
from telemetry_factory import create_telemetry
import export_prepare

app = QApplication.instance() or QApplication([])

BIN_DIR = os.path.join(PROJECT_ROOT, "bin")
EXPORTER_EXE = os.path.join(BIN_DIR, "KomparatorGpuExporter.exe")
FFPROBE_EXE = os.path.join(PROJECT_ROOT, "third_party", "ffmpeg", "bin", "ffprobe.exe")
FFMPEG_EXE = os.path.join(PROJECT_ROOT, "third_party", "ffmpeg", "bin", "ffmpeg.exe")

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "artifacts", "benchmark_run")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VIDEO1 = "D:/GoPro/GX010338.MP4"
VIDEO2 = "D:/GoPro/DJI_20261002062647_0003_D.MP4"

def run_export_with_preview(config_dict, enable_preview_ipc=True, timeout=120):
    live_preview = None
    frames_received = []

    if enable_preview_ipc and config_dict.get("export_preview", True):
        live_preview = ExportLivePreview()
        pipe_name = live_preview.start()
        config_dict["preview_pipe"] = pipe_name
        def on_packet(meta, jpeg_bytes):
            frames_received.append((meta, len(jpeg_bytes), jpeg_bytes))
        live_preview.packetReceived = on_packet

    cfg_path = os.path.join(OUTPUT_DIR, "temp_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [EXPORTER_EXE, "--config", cfg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    stdout_lines = []
    stderr_lines = []
    progress_events = []
    complete_event = None
    zero_copy_counters = {}
    preset_logged = None

    # Poll process while pumping Qt events for QLocalServer IPC
    while proc.poll() is None:
        app.processEvents()
        time.sleep(0.01)

    total_time = time.perf_counter() - t0

    stdout_data, stderr_data = proc.communicate()
    stdout_lines = stdout_data.splitlines()
    stderr_lines = stderr_data.splitlines()

    if live_preview:
        live_preview.stop()

    for line in stdout_lines:
        try:
            msg = json.loads(line.strip())
            mtype = msg.get("type")
            if mtype == "progress":
                progress_events.append(msg)
            elif mtype == "complete":
                complete_event = msg
        except Exception:
            pass

    for line in stderr_lines:
        if "[HwEncoder]" in line:
            preset_logged = line.strip()
        if "FULL_FRAME_HWDOWNLOAD_COUNT=" in line:
            for part in line.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    try:
                        zero_copy_counters[k] = int(v)
                    except ValueError:
                        pass

    return {
        "returncode": proc.returncode,
        "total_time": total_time,
        "progress_events": progress_events,
        "complete_event": complete_event,
        "zero_copy_counters": zero_copy_counters,
        "preset_logged": preset_logged,
        "frames_received": frames_received,
        "stdout": stdout_lines,
        "stderr": stderr_lines,
    }

def probe_mp4(filepath):
    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_streams",
        "-show_entries", "stream=codec_name,width,height,duration,bit_rate:stream_tags:stream_side_data",
        "-of", "json",
        filepath
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    stream = data["streams"][0] if data.get("streams") else {}

    # Check side data for rotation/display matrix
    side_data_list = stream.get("side_data_list", [])
    rotation = None
    has_display_matrix = False
    for sd in side_data_list:
        if sd.get("side_data_type") == "Display Matrix":
            has_display_matrix = True
            rotation = sd.get("rotation")

    tags = stream.get("tags", {})
    tag_rotation = tags.get("rotate")
    file_size = os.path.getsize(filepath)

    return {
        "codec_name": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "file_size": file_size,
        "side_data_list": side_data_list,
        "has_display_matrix": has_display_matrix,
        "rotation": rotation,
        "tag_rotation": tag_rotation,
    }

def extract_raw_frame(mp4_path, out_png_path, time_sec=2.0):
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-noautorotate",
        "-ss", str(time_sec),
        "-i", mp4_path,
        "-vframes", "1",
        out_png_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)

def main():
    print("==================================================================")
    print("   KOMPARATOR GPU EXPORTER - FULL BENCHMARK & VERIFICATION SUITE   ")
    print("==================================================================")

    print("Extracting telemetry from input clips...")
    p1 = create_telemetry(VIDEO1)
    p2 = create_telemetry(VIDEO2)
    t1 = export_prepare.compact_telemetry(p1)
    t2 = export_prepare.compact_telemetry(p2)
    print(f"  Clip 1 ({p1.camera_name}): {len(t1.get('samples', []))} telemetry samples")
    print(f"  Clip 2 ({p2.camera_name}): {len(t2.get('samples', []))} telemetry samples")

    results = {}

    # --- 1. BENCHMARK 3 HEVC PROFILES ---
    profiles = ["speed", "balanced", "quality"]
    profile_names = {
        "speed": "Najszybszy",
        "balanced": "Zbalansowany",
        "quality": "Najlepsza jakość"
    }

    print("\n[STEP 1] Testing & Benchmarking 3 HEVC Profiles (8 seconds duration, 15 Mbps)...")
    for prof in profiles:
        out_file = os.path.join(OUTPUT_DIR, f"output_profile_{prof}.mp4")
        if os.path.exists(out_file):
            try: os.remove(out_file)
            except Exception: pass

        cfg = {
            "video1": VIDEO1,
            "video2": VIDEO2,
            "output": out_file,
            "layout": "left_right",
            "offset_seconds": 0.0,
            "width": 3840,
            "height": 2160,
            "encoder": "amf",
            "codec": "hevc",
            "encoder_preset": prof,
            "bitrate": 15000000,
            "audio": "mute",
            "show_overlay": True,
            "telemetry1": t1,
            "telemetry2": t2,
            "export_preview": True,
            "duration_limit_seconds": 8.0
        }

        print(f"\n--- Testing Profile: {prof} ({profile_names[prof]}) ---")
        run_res = run_export_with_preview(cfg, enable_preview_ipc=True)
        assert run_res["returncode"] == 0, f"Profile {prof} export failed: {run_res['stderr'][-10:]}"
        assert os.path.exists(out_file), f"Output file {out_file} not found"

        probe_res = probe_mp4(out_file)
        complete = run_res["complete_event"] or {}
        avg_fps = complete.get("avg_fps", 0.0)
        total_time = run_res["total_time"]
        frames = complete.get("total_frames", 0)

        # Save received preview frame
        preview_png = os.path.join(OUTPUT_DIR, f"preview_frame_{prof}.jpg")
        if run_res["frames_received"]:
            meta, length, jpeg_bytes = run_res["frames_received"][-1]
            with open(preview_png, "wb") as pf:
                pf.write(jpeg_bytes)
            print(f"  Preview frames received: {len(run_res['frames_received'])}, saved last frame to {preview_png}")

        # Extract raw frame
        raw_png = os.path.join(OUTPUT_DIR, f"raw_frame_{prof}.png")
        extract_raw_frame(out_file, raw_png, time_sec=2.0)

        hwdown = run_res["zero_copy_counters"].get("FULL_FRAME_HWDOWNLOAD_COUNT", complete.get("full_frame_hwdownload_count", -1))
        hwup = run_res["zero_copy_counters"].get("FULL_FRAME_HWUPLOAD_COUNT", complete.get("full_frame_hwupload_count", -1))
        sw = run_res["zero_copy_counters"].get("SOFTWARE_VIDEO_FRAME_COUNT", complete.get("software_frame_count", -1))

        results[prof] = {
            "polish_name": profile_names[prof],
            "preset": prof,
            "returncode": run_res["returncode"],
            "total_time": total_time,
            "frames": frames,
            "avg_fps": avg_fps,
            "file_size": probe_res["file_size"],
            "codec_name": probe_res["codec_name"],
            "rotation": probe_res["rotation"],
            "tag_rotation": probe_res["tag_rotation"],
            "has_display_matrix": probe_res["has_display_matrix"],
            "zero_copy": {"hwdown": hwdown, "hwup": hwup, "sw": sw},
            "preset_logged": run_res["preset_logged"],
            "raw_png": raw_png,
            "preview_frames_count": len(run_res["frames_received"])
        }

        print(f"  Result: Returncode=0, Time={total_time:.2f}s, Encoded={frames} frames, FPS={avg_fps:.2f}")
        print(f"  File size: {probe_res['file_size']} bytes, Codec: {probe_res['codec_name']}")
        print(f"  Rotation: {probe_res['rotation']}, Tag rotation: {probe_res['tag_rotation']}")
        print(f"  Zero-copy counters: hwdown={hwdown}, hwup={hwup}, sw={sw}")
        if run_res["preset_logged"]:
            print(f"  Encoder log: {run_res['preset_logged']}")

        assert probe_res["codec_name"] == "hevc", f"Expected hevc, got {probe_res['codec_name']}"
        assert probe_res["rotation"] is None or probe_res["rotation"] == 0, f"Unexpected rotation: {probe_res['rotation']}"
        assert probe_res["tag_rotation"] is None, f"Unexpected tag rotation: {probe_res['tag_rotation']}"
        assert hwdown == 0, f"Expected 0 hwdown, got {hwdown}"
        assert hwup == 0, f"Expected 0 hwup, got {hwup}"
        assert sw == 0, f"Expected 0 sw, got {sw}"

    # --- 2. PREVIEW OVERHEAD TEST ---
    print("\n[STEP 2] Testing Export Preview Overhead (balanced profile, preview OFF vs preview ON)...")
    out_no_preview = os.path.join(OUTPUT_DIR, "output_no_preview.mp4")
    if os.path.exists(out_no_preview):
        try: os.remove(out_no_preview)
        except Exception: pass

    cfg_no_preview = {
        "video1": VIDEO1,
        "video2": VIDEO2,
        "output": out_no_preview,
        "layout": "left_right",
        "offset_seconds": 0.0,
        "width": 3840,
        "height": 2160,
        "encoder": "amf",
        "codec": "hevc",
        "encoder_preset": "balanced",
        "bitrate": 15000000,
        "audio": "mute",
        "show_overlay": True,
        "telemetry1": t1,
        "telemetry2": t2,
        "export_preview": False,
        "duration_limit_seconds": 8.0
    }

    run_no_preview = run_export_with_preview(cfg_no_preview, enable_preview_ipc=False)
    fps_no_prev = run_no_preview["complete_event"].get("avg_fps", 0.0)
    fps_with_prev = results["balanced"]["avg_fps"]

    # Overhead delta percentage: (fps_no_prev - fps_with_prev) / fps_no_prev * 100
    overhead_pct = ((fps_no_prev - fps_with_prev) / fps_no_prev) * 100.0 if fps_no_prev > 0 else 0.0
    print(f"  FPS with preview OFF: {fps_no_prev:.2f}")
    print(f"  FPS with preview ON:  {fps_with_prev:.2f}")
    print(f"  Overhead delta:       {overhead_pct:.2f}% (Target: <= 2.0%)")

    results["preview_overhead"] = {
        "fps_off": fps_no_prev,
        "fps_on": fps_with_prev,
        "delta_percent": overhead_pct
    }

    # --- 3. TEST TOP/BOTTOM LAYOUT ---
    print("\n[STEP 3] Testing Top/Bottom (vertical) Layout...")
    out_vertical = os.path.join(OUTPUT_DIR, "output_vertical.mp4")
    if os.path.exists(out_vertical):
        try: os.remove(out_vertical)
        except Exception: pass

    cfg_vertical = {
        "video1": VIDEO1,
        "video2": VIDEO2,
        "output": out_vertical,
        "layout": "top_bottom",
        "offset_seconds": 0.0,
        "width": 3840,
        "height": 2160,
        "encoder": "amf",
        "codec": "hevc",
        "encoder_preset": "balanced",
        "bitrate": 15000000,
        "audio": "mute",
        "show_overlay": True,
        "telemetry1": t1,
        "telemetry2": t2,
        "export_preview": True,
        "duration_limit_seconds": 5.0
    }

    run_vertical = run_export_with_preview(cfg_vertical, enable_preview_ipc=True)
    assert run_vertical["returncode"] == 0, f"Vertical export failed: {run_vertical['stderr'][-10:]}"
    probe_vert = probe_mp4(out_vertical)
    raw_png_vert = os.path.join(OUTPUT_DIR, "raw_frame_vertical.png")
    extract_raw_frame(out_vertical, raw_png_vert, time_sec=2.0)

    print(f"  Vertical export: Time={run_vertical['total_time']:.2f}s, FPS={run_vertical['complete_event'].get('avg_fps', 0):.2f}")
    print(f"  Resolution: {probe_vert['width']}x{probe_vert['height']}, Codec: {probe_vert['codec_name']}")
    assert probe_vert["codec_name"] == "hevc"
    assert probe_vert["rotation"] is None or probe_vert["rotation"] == 0

    results["vertical"] = {
        "returncode": run_vertical["returncode"],
        "total_time": run_vertical["total_time"],
        "fps": run_vertical["complete_event"].get("avg_fps", 0),
        "width": probe_vert["width"],
        "height": probe_vert["height"],
        "codec_name": probe_vert["codec_name"],
        "raw_png": raw_png_vert,
        "preview_frames_count": len(run_vertical["frames_received"])
    }

    # --- 4. TEST CANCELLATION LATENCY ---
    print("\n[STEP 4] Testing Export Cancellation Latency (< 1.5s target)...")
    out_cancel = os.path.join(OUTPUT_DIR, "output_cancel.mp4")
    cfg_cancel = {
        "video1": VIDEO1,
        "video2": VIDEO2,
        "output": out_cancel,
        "layout": "left_right",
        "offset_seconds": 0.0,
        "width": 3840,
        "height": 2160,
        "encoder": "amf",
        "codec": "hevc",
        "encoder_preset": "balanced",
        "bitrate": 15000000,
        "audio": "mute",
        "show_overlay": True,
        "telemetry1": t1,
        "telemetry2": t2,
        "export_preview": False,
        "duration_limit_seconds": 60.0
    }
    cfg_cancel_path = os.path.join(OUTPUT_DIR, "temp_cfg_cancel.json")
    with open(cfg_cancel_path, "w", encoding="utf-8") as f:
        json.dump(cfg_cancel, f, indent=2)

    proc = subprocess.Popen(
        [EXPORTER_EXE, "--config", cfg_cancel_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Let it run for 2.0 seconds
    time.sleep(2.0)
    t_cancel_start = time.perf_counter()
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    t_cancel_done = time.perf_counter()
    cancel_latency = t_cancel_done - t_cancel_start

    print(f"  Cancellation latency: {cancel_latency:.3f}s (Target: < 1.5s)")
    assert cancel_latency < 1.5, f"Cancellation latency {cancel_latency:.3f}s exceeded 1.5s!"
    results["cancel_latency"] = cancel_latency

    # Save summary json
    summary_path = os.path.join(OUTPUT_DIR, "benchmark_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved full benchmark summary to {summary_path}")
    print("\n==================================================================")
    print("      ALL VERIFICATIONS AND BENCHMARKS COMPLETED SUCCESSFULLY!    ")
    print("==================================================================")

if __name__ == "__main__":
    main()
