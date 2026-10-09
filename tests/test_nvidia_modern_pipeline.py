import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import export_prepare
import nvidia_modern
from backend_benchmark import BackendSelector
import backend_benchmark


def _build(layout="top_bottom", dual4k=False, preset="balanced", pad=True):
    return nvidia_modern.build_command(
        ffmpeg_exe=r"K:\Comparator\runtime\nvidia\ffmpeg\ffmpeg.exe",
        video_paths=(r"K:\media\one.mp4", r"K:\media\two.mp4"),
        output=r"K:\out\result.mp4", layout=layout, input_size=(3840, 2160),
        scale=1.0, dual4k=dual4k, preset=preset, bitrate_mbps=17.5,
        duration=12.0, delays=(0.0, 0.25), audio_present=(True, True),
        audio_mode="both", ass_paths=(r"K:\tmp\one.ass", r"K:\tmp\two.ass"),
        pad_to_4k=pad,
    )


def test_modern_top_bottom_scales_before_download_and_uses_p4_gui_bitrate():
    args, output_size = _build()
    cmd = nvidia_modern.command_for_log(r"K:\ffmpeg.exe", args)
    assert output_size == (3840, 2160)
    assert args.count("-hwaccel") == 2
    assert args.count("cuda") >= 4
    graph = args[args.index("-filter_complex") + 1]
    assert "scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12" in graph
    assert graph.index("scale_cuda") < graph.index("hwdownload")
    assert "vstack=inputs=2" in graph
    assert "pad=3840:2160" in graph
    assert r"ass=filename='K\:/tmp/one.ass'" in graph
    assert args[args.index("-c:v") + 1] == "hevc_nvenc"
    assert args[args.index("-preset") + 1] == "p4"
    assert args[args.index("-b:v") + 1] == "17.5M"
    assert "-split_encode_mode" not in args
    assert "hwupload_cuda" not in graph
    assert "FFMPEG_COMMAND=" not in cmd  # the logger adds the prefix separately


def test_modern_left_right_uses_hstack():
    args, output_size = _build(layout="left_right")
    assert output_size == (3840, 2160)
    graph = args[args.index("-filter_complex") + 1]
    assert "hstack=inputs=2" in graph
    assert "vstack" not in graph
    assert "pad=3840:2160" in graph


@pytest.mark.parametrize("layout", ["left_right", "top_bottom"])
@pytest.mark.parametrize("pad", [True, False])
def test_modern_preview_is_sampled_at_5fps_before_export_pad_and_uses_tcp(layout, pad):
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout=layout, input_size=(3840, 2160), scale=1.0, dual4k=False,
        preset="balanced", bitrate_mbps=10, duration=2, delays=(0, 0),
        audio_present=(False, False), audio_mode="mute", ass_paths=(None, None),
        pad_to_16_9=pad, preview_port=45123, preview_size=(1280, 720),
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "fps=5,scale=1280:720:force_original_aspect_ratio=decrease" in graph
    assert "[stacked_fps]split=2[export_source][preview_source]" in graph
    split_at = graph.index("[stacked_fps]split=2[export_source][preview_source]")
    preview_at = graph.index("[preview_source]fps=5")
    assert split_at < preview_at
    if pad:
        pad_at = graph.index("[export_source]pad=3840:2160")
        assert split_at < pad_at < preview_at
    else:
        assert "[export_source]null[v]" in graph
    assert "[preview_source]pad=" not in graph
    assert graph.index("[composite]setpts=") < split_at
    assert "fps=30[stacked_fps]" in graph
    assert args[-1] == "tcp://127.0.0.1:45123?tcp_nodelay=1"
    assert "-drop_pkts_on_overflow" in args
    assert "udp://" not in " ".join(args)


@pytest.mark.parametrize("resolution", ["2160p", "dual4k"])
@pytest.mark.parametrize("layout", ["left_right", "top_bottom"])
@pytest.mark.parametrize("speed", [1, 2, 4])
@pytest.mark.parametrize("pad", [False, True])
def test_preview_keeps_composition_aspect_across_resolution_speed_and_padding(resolution, layout, speed, pad):
    dual4k = resolution == "dual4k"
    args, output_size = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout=layout, input_size=(3840, 2160), scale=1.0, dual4k=dual4k,
        preset="balanced", bitrate_mbps=10, duration=10, delays=(0, 0),
        audio_present=(False, False), audio_mode="mute", ass_paths=(None, None),
        pad_to_16_9=pad, playback_speed=speed, output_fps=59.94,
        preview_port=45123, preview_size=(1568, 882),
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "[stacked_fps]split=2[export_source][preview_source]" in graph
    assert "[preview_source]fps=5,scale=1568:882:force_original_aspect_ratio=decrease" in graph
    assert "[preview_source]pad=" not in graph
    if pad and not dual4k:
        assert "[export_source]pad=3840:2160" in graph
    if dual4k and pad:
        assert "-split_encode_mode" in args
        assert args[args.index("-split_encode_mode") + 1] == "forced"
    assert output_size[0] > 0 and output_size[1] > 0
    assert "[composite]setpts=(PTS-STARTPTS)/" + str(speed) in graph if speed > 1 else "[composite]setpts=PTS-STARTPTS" in graph
    assert graph.index("[composite]setpts=") < graph.index("[stacked_fps]split=")
    assert args[-1] == "tcp://127.0.0.1:45123?tcp_nodelay=1"


@pytest.mark.parametrize("dual4k", [False, True])
@pytest.mark.parametrize("layout", ["left_right", "top_bottom"])
@pytest.mark.parametrize("pad", [False, True])
def test_ffmpeg_thumbnail_scaler_fits_camera_composite_without_distortion(dual4k, layout, pad):
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout=layout, input_size=(3840, 2160), scale=1.0, dual4k=dual4k,
        preset="balanced", bitrate_mbps=10, duration=2, delays=(0, 0),
        audio_present=(False, False), audio_mode="mute", ass_paths=(None, None),
        pad_to_16_9=pad, preview_port=45123, preview_size=(1000, 700),
    )
    graph = args[args.index("-filter_complex") + 1]
    stack_dimensions = (7680, 2160) if dual4k and layout == "left_right" else (
        (3840, 4320) if dual4k else
        ((3840, 1080) if layout == "left_right" else (1920, 2160))
    )
    assert "scale=1000:700:force_original_aspect_ratio=decrease" in graph
    assert graph.index("[stacked_fps]split=") < graph.index("[preview_source]fps=5,scale=")
    if pad:
        assert graph.index("[stacked_fps]split=") < graph.index("[export_source]pad=")
    preview_filter = graph[graph.index("[preview_source]fps=5,scale="):]
    assert "pad=" not in preview_filter
    requested_ratio = 1000 / 700
    expected_scale = min(requested_ratio / (stack_dimensions[0] / stack_dimensions[1]), 1)
    expected_size = (int(stack_dimensions[0] * expected_scale), int(stack_dimensions[1] * expected_scale))
    actual_ratio = expected_size[0] / expected_size[1]
    source_ratio = stack_dimensions[0] / stack_dimensions[1]
    assert abs(actual_ratio - source_ratio) / source_ratio < 0.01


def test_old_scale_helper_is_not_used_to_change_output_geometry():
    assert nvidia_modern.modern_input_size(3840, 2160, "top_bottom", 1.0) == (1920, 1080)
    assert nvidia_modern.modern_input_size(3840, 2160, "top_bottom", 0.5) == (1920, 1080)
    assert nvidia_modern.modern_input_size(3840, 2160, "top_bottom", 0.25) == (960, 540)
    assert nvidia_modern.modern_input_size(3840, 2160, "left_right", 1.0) == (1920, 1080)


@pytest.mark.parametrize(
    ("mode", "audio_filter_count"),
    [("mute", 0), ("left", 1), ("right", 1), ("both", 2)],
)
def test_modern_audio_selector_keeps_mute_left_right_and_both(mode, audio_filter_count):
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout="top_bottom", input_size=(3840, 2160), scale=1.0, dual4k=False,
        preset="balanced", bitrate_mbps=10.0, duration=2.0, delays=(0.0, 0.1),
        audio_present=(True, True), audio_mode=mode, ass_paths=(None, None), pad_to_4k=False,
    )
    graph = args[args.index("-filter_complex") + 1]
    assert graph.count("asetpts=") == audio_filter_count
    assert ("-map" in args and "[a]" in args) is (audio_filter_count > 0)


@pytest.mark.parametrize(
    ("layout", "expected"),
    [("top_bottom", (7680, 4320)), ("left_right", (7680, 4320))],
)
def test_dual4k_preserves_each_input_and_forces_split(layout, expected):
    args, output_size = _build(layout=layout, dual4k=True, pad=True)
    graph = args[args.index("-filter_complex") + 1]
    assert output_size == expected
    assert graph.count("scale_cuda=format=nv12,hwdownload,format=nv12") == 2
    assert ("vstack=inputs=2" if layout == "top_bottom" else "hstack=inputs=2") in graph
    assert args[args.index("-split_encode_mode") + 1] == "forced"
    assert args[args.index("-preset") + 1] == "p4"
    assert "pad=3840:2160" not in graph


@pytest.mark.parametrize(("preset", "ffpreset"), [("speed", "p2"), ("balanced", "p4"), ("quality", "p6")])
def test_preset_mapping(preset, ffpreset):
    args, _ = _build(preset=preset)
    assert args[args.index("-preset") + 1] == ffpreset


def test_nvidia_balanced_legacy_benchmark_explicitly_passes_p4(monkeypatch):
    captured = {}
    monkeypatch.setattr(backend_benchmark.video_encoder, "resolve_legacy_ffmpeg", lambda _hw: "ffmpeg")
    def fake_run(command, **_kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, b"", b"")
    monkeypatch.setattr(backend_benchmark.subprocess, "run", fake_run)
    assert BackendSelector.benchmark_legacy("NVIDIA", "hevc_nvenc", 1920, 1080) > 0
    command = captured["command"]
    assert command[command.index("-preset") + 1] == "p4"


def test_standard_output_is_always_padded_to_2160p():
    args, output_size = _build(pad=True)
    graph = args[args.index("-filter_complex") + 1]
    assert output_size == (3840, 2160)
    assert "pad=3840:2160" in graph


class _Provider:
    def __init__(self, filename):
        self.filename = filename

    def generate_ass(self, *_args, **_kwargs):
        return ""


def _mock_ffprobe(monkeypatch):
    payload = {
        "format": {"duration": "8.0"},
        "streams": [
            {"codec_type": "video", "width": 3840, "height": 2160},
            {"codec_type": "audio"},
        ],
    }
    monkeypatch.setattr(
        export_prepare.subprocess, "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )


def _options(tmp_path, backend=0, dual=False):
    return {
        "scale": 1.0, "dual_4k": dual, "hw": "NVIDIA", "backend": backend,
        "preset": "Balanced", "output": str(tmp_path / "out.mp4"), "layout": "top_bottom",
        "offset": 0, "bitrate": 10.0, "audio": "both", "overlay": False,
        "export_preview": False, "preview_pipe": "", "pad_to_4k": True,
    }


def test_auto_selects_modern_and_generates_full_command(monkeypatch, tmp_path):
    _mock_ffprobe(monkeypatch)
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffmpeg", lambda _hw: "ffmpeg-nvidia")
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_modern", lambda *_a: (True, ""))
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_dual4k", lambda *_a: (True, ""))
    monkeypatch.setattr(export_prepare, "resolve_export_helper", lambda *_a: (None, None))
    result = export_prepare.prepare_export(
        _options(tmp_path), [_Provider("one.mp4"), _Provider("two.mp4")], tmp_path
    )
    assert result[0] == "legacy"  # FFmpeg remains the process mode.
    assert result[4] == "NVIDIA_MODERN_FFMPEG"
    args = result[2]
    graph = args[args.index("-filter_complex") + 1]
    assert "scale_cuda=1920:1080" in graph
    assert args[args.index("-preset") + 1] == "p4"


def test_modern_failure_falls_back_to_legacy(monkeypatch, tmp_path):
    _mock_ffprobe(monkeypatch)
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffmpeg", lambda _hw: "ffmpeg-nvidia")
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_modern", lambda *_a: (False, "no CUDA"))
    monkeypatch.setattr(export_prepare, "resolve_export_helper", lambda *_a: (None, None))
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_a: True)
    monkeypatch.setattr(export_prepare, "probe_encoder_limit", lambda *_a: (3840, 2160))
    result = export_prepare.prepare_export(
        _options(tmp_path), [_Provider("one.mp4"), _Provider("two.mp4")], tmp_path
    )
    assert result[4] == "NVIDIA_LEGACY"
    graph = result[2][result[2].index("-filter_complex") + 1]
    assert "scale_cuda" not in graph


def test_dual4k_falls_back_to_legacy_encoder_when_modern_split_probe_fails(monkeypatch, tmp_path):
    _mock_ffprobe(monkeypatch)
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffmpeg", lambda _hw: "ffmpeg-nvidia")
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_modern", lambda *_a: (True, ""))
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_dual4k", lambda *_a: (False, "no 8k"))
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_a: True)
    monkeypatch.setattr(export_prepare.video_encoder, "probe_encoder_size", lambda *_a: (True, "PASS"))
    result = export_prepare.prepare_export(
        _options(tmp_path, dual=True), [_Provider("one.mp4"), _Provider("two.mp4")], tmp_path
    )
    assert result[4] == "NVIDIA_LEGACY"
    assert "-split_encode_mode" not in result[2]


def test_unsupported_dual4k_probe_is_cached_and_contains_forced_split(monkeypatch):
    nvidia_modern._CACHE.clear()
    seen = []
    def fail_large_encode(command, **_kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 1, "", "unsupported dimensions")
    monkeypatch.setattr(nvidia_modern.subprocess, "run", fail_large_encode)
    first = nvidia_modern.probe_nvidia_dual4k("ffmpeg-test", "top_bottom", "balanced")
    second = nvidia_modern.probe_nvidia_dual4k("ffmpeg-test", "top_bottom", "balanced")
    assert first[0] is False and second == first
    assert len(seen) == 1
    command = seen[0]
    assert any("7680x4320" in str(arg) for arg in command)
    assert command[command.index("-preset") + 1] == "p4"
    assert command[command.index("-split_encode_mode") + 1] == "forced"


def test_modern_always_requires_real_source_p4_probe(monkeypatch, tmp_path):
    nvidia_modern._CACHE.clear()
    monkeypatch.setattr(
        nvidia_modern, "detect_nvidia_gpu_info",
        lambda: nvidia_modern.classify_nvidia_gpu("RTX 5070 Ti", (12, 0)),
    )
    seen = []
    def fail_p4(command, **_kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 1, "", "p4 unavailable")
    monkeypatch.setattr(nvidia_modern.subprocess, "run", fail_p4)
    ok, detail = nvidia_modern.probe_nvidia_modern("ffmpeg-test", str(tmp_path / "source.mp4"), "speed")
    assert not ok
    assert "p4" in detail
    assert len(seen) == 1
    assert seen[0][seen[0].index("-preset") + 1] == "p4"


@pytest.mark.parametrize(
    ("name", "capability", "expected"),
    [
        ("Quadro P400", (6, 1), "LEGACY"),
        ("RTX 20xx", (7, 5), "MODERN"),
        ("RTX 30xx", (8, 6), "MODERN"),
        ("RTX 40xx", (8, 9), "MODERN"),
        ("RTX 50xx", (12, 0), "MODERN"),
    ],
)
def test_gpu_architecture_classification(name, capability, expected):
    info = nvidia_modern.classify_nvidia_gpu(name, capability)
    assert info["architecture_class"] == expected


def test_simulated_quadro_p400_stays_legacy_even_if_ffmpeg_would_pass(monkeypatch):
    monkeypatch.setattr(
        nvidia_modern, "detect_nvidia_gpu_info",
        lambda: nvidia_modern.classify_nvidia_gpu("Quadro P400", (6, 1)),
    )
    monkeypatch.setattr(
        nvidia_modern, "_probe_nvidia_modern_preset",
        lambda *_args: pytest.fail("Legacy architecture must not reach the FFmpeg probe"),
    )
    ok, reason = nvidia_modern.probe_nvidia_modern("ffmpeg", "source.mp4", "balanced")
    assert not ok
    assert "LEGACY" in reason


def test_unknown_gpu_generation_fails_closed_to_legacy():
    info = nvidia_modern.classify_nvidia_gpu("Unknown NVIDIA", None)
    assert info["architecture_class"] == "LEGACY"
    assert info["reason"] == "COMPUTE_CAPABILITY_UNKNOWN_SAFE_LEGACY"


def test_forced_legacy_does_not_call_modern_probe(monkeypatch, tmp_path):
    _mock_ffprobe(monkeypatch)
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffmpeg", lambda _hw: "ffmpeg-nvidia")
    def unexpected(*_a):
        raise AssertionError("forced Legacy must skip NVIDIA Modern")
    monkeypatch.setattr(export_prepare.nvidia_modern, "probe_nvidia_modern", unexpected)
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_a: True)
    monkeypatch.setattr(export_prepare, "probe_encoder_limit", lambda *_a: (3840, 2160))
    result = export_prepare.prepare_export(
        _options(tmp_path, backend=2), [_Provider("one.mp4"), _Provider("two.mp4")], tmp_path
    )
    assert result[4] == "NVIDIA_LEGACY"
