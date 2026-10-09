import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import export_prepare
import nvidia_modern


class Provider:
    def __init__(self, filename):
        self.filename = filename

    def generate_ass(self, *_args, **_kwargs):
        return ""


@pytest.mark.parametrize("resolution", ["2160p", "dual4k"])
@pytest.mark.parametrize("layout", ["top_bottom", "left_right"])
@pytest.mark.parametrize("speed", [1, 2, 4])
def test_modern_pipeline_has_12_resolution_layout_speed_combinations(resolution, layout, speed):
    dual = resolution == "dual4k"
    args, size = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout=layout, input_size=(3840, 2160), scale=.25, dual4k=dual,
        preset="balanced", bitrate_mbps=10, duration=10, delays=(0, 0),
        audio_present=(True, True), audio_mode="both", ass_paths=(None, None),
        pad_to_4k=False, playback_speed=speed, output_fps=59.94,
    )
    expected_size = ((7680, 2160) if layout == "left_right" else (3840, 4320)) if dual else ((3840, 1080) if layout == "left_right" else (1920, 2160))
    assert size == expected_size
    graph = args[args.index("-filter_complex") + 1]
    stack = "hstack=inputs=2" if layout == "left_right" else "vstack=inputs=2"
    assert stack in graph
    final_speed = graph.index(f"[composite]setpts=(PTS-STARTPTS)/{speed}") if speed > 1 else graph.index("[composite]setpts=PTS-STARTPTS")
    assert graph.index(stack) < final_speed < graph.index("fps=59.94")
    assert args[args.index("-t") + 1] == str(10 / speed)
    assert args[args.index("-r") + 1] == "59.94"
    assert ("-split_encode_mode" in args) is dual
    assert graph.count("atempo=2") == (2 if speed == 4 else 1 if speed == 2 else 0)
    assert "pad=3840:2160" not in graph


@pytest.mark.parametrize("resolution", ["2160p", "dual4k"])
@pytest.mark.parametrize("layout", ["top_bottom", "left_right"])
@pytest.mark.parametrize("speed", [1, 2, 4])
def test_cpu_ffmpeg_uses_exact_canvas_and_effective_duration(monkeypatch, tmp_path, resolution, layout, speed):
    dual = resolution == "dual4k"
    payload = {"format": {"duration": "10"}, "streams": [
        {"codec_type": "video", "width": 3840, "height": 2160,
         "avg_frame_rate": "30000/1001", "r_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ]}
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_a: True)
    monkeypatch.setattr(export_prepare, "probe_encoder_limit", lambda *_a: (3840, 2160))
    monkeypatch.setattr(export_prepare.video_encoder, "probe_encoder_size", lambda *_a: (True, "PASS"))
    options = {
        "playback_speed": speed, "pad_to_16_9": False, "scale": .25, "dual_4k": dual, "hw": "CPU", "backend": 2,
        "preset": "balanced", "output": str(tmp_path / "out.mp4"), "layout": layout,
        "offset": 0, "bitrate": 10, "audio": "both", "overlay": False,
    }
    result = export_prepare.prepare_export(options, [Provider("one.mp4"), Provider("two.mp4")], tmp_path)
    assert result[3] == pytest.approx(10 / speed)
    args = result[2]
    graph = args[args.index("-filter_complex") + 1]
    assert args[args.index("-t") + 1] == str(10 / speed)
    assert ("setpts=(PTS-STARTPTS)/" + str(speed)) in graph if speed > 1 else "setpts=PTS-STARTPTS" in graph
    assert "fps=29.97" in graph
    assert graph.count("atempo=2") == (2 if speed == 4 else 1 if speed == 2 else 0)
    assert "pad=3840:2160" not in graph


@pytest.mark.parametrize("audio_mode,expected_sources", [("mute", 0), ("left", 1), ("right", 1), ("both", 2)])
@pytest.mark.parametrize("speed,tempo_filters", [(1, 0), (2, 1), (4, 2)])
def test_modern_audio_selection_and_tempo_are_applied_after_mix(audio_mode, expected_sources, speed, tempo_filters):
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("one.mp4", "two.mp4"), output="out.mp4",
        layout="top_bottom", input_size=(3840, 2160), scale=1, dual4k=False,
        preset="balanced", bitrate_mbps=10, duration=10, delays=(0, .5),
        audio_present=(True, True), audio_mode=audio_mode, ass_paths=("one.ass", "two.ass"),
        pad_to_4k=False, playback_speed=speed, output_fps=30,
    )
    graph = args[args.index("-filter_complex") + 1]
    assert graph.count("[0:a]") + graph.count("[1:a]") == expected_sources
    assert graph.count("atempo=2") == (0 if audio_mode == "mute" else tempo_filters)
    speed_filter = graph.index("[composite]setpts=")
    assert graph.index("ass=filename") < graph.index("vstack=inputs=2") < speed_filter
    assert "[a]" in args if expected_sources else "[a]" not in args


def test_unsupported_standard_canvas_fails_without_silent_downscale(monkeypatch, tmp_path):
    payload = {"format": {"duration": "1"}, "streams": [
        {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
    ]}
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_a: True)
    monkeypatch.setattr(export_prepare, "probe_encoder_limit", lambda *_a: (2560, 1440))
    options = {
        "playback_speed": 1, "scale": .25, "dual_4k": False, "hw": "AMD AMF", "backend": 2,
        "preset": "balanced", "output": str(tmp_path / "out.mp4"), "layout": "left_right",
        "offset": 0, "bitrate": 10, "audio": "mute", "overlay": False,
    }
    with pytest.raises(RuntimeError, match="Nie zmieniono rozdzielczości"):
        export_prepare.prepare_export(options, [Provider("one.mp4"), Provider("two.mp4")], tmp_path)
