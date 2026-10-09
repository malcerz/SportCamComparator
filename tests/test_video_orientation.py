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
from video_orientation import inspect_orientation


def _stream(rotation=None, tag=None, displaymatrix=True):
    stream = {"codec_type": "video", "width": 3840, "height": 2160, "avg_frame_rate": "30/1"}
    if tag is not None:
        stream["tags"] = {"rotate": str(tag)}
    if displaymatrix:
        stream["side_data_list"] = [{
            "side_data_type": "Display Matrix",
            "rotation": rotation,
            "displaymatrix": "\n00000000: 65536 0 0\n00000001: 0 65536 0",
        }]
    return stream


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0, ""), (90, "transpose=cclock"), (180, "hflip,vflip"), (270, "transpose=clock"),
     (-180, "hflip,vflip"), (-90, "transpose=clock")],
)
def test_orientation_maps_ffprobe_displaymatrix_to_explicit_pixel_filter(angle, expected):
    info = inspect_orientation(_stream(angle))
    assert info["filter"] == expected
    assert info["correction"] == angle % 360
    assert info["displaymatrix_rotation"] == float(angle)


def test_simulated_quadro_p400_pascal_clip_rotated_180_is_flipped_before_ass():
    # The GPU model does not affect orientation parsing; this simulates the
    # P400/Pascal clip's FFprobe display-matrix signature.
    info = inspect_orientation(_stream(-180))
    assert info["filter"] == "hflip,vflip"
    assert info["normalized"] is True


def test_orientation_prefers_displaymatrix_and_warns_on_unknown_or_non_quarter_turn():
    unknown = _stream(None, tag=90)
    unknown["side_data_list"][0]["displaymatrix"] = "malformed matrix"
    assert inspect_orientation(unknown)["decision"].startswith("WARN_DISPLAYMATRIX_UNSUPPORTED")
    conflict = inspect_orientation(_stream(180, tag=90))
    assert conflict["filter"] == "hflip,vflip"
    assert conflict["warning"] is True
    unsupported = inspect_orientation({"tags": {"rotate": "45"}})
    assert unsupported["warning"] is True and unsupported["normalized"] is False


def test_modern_does_not_claim_unknown_orientation_was_normalized():
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("a.mp4", "b.mp4"), output="out.mp4",
        layout="top_bottom", input_size=(3840, 2160), scale=1, dual4k=False,
        preset="balanced", bitrate_mbps=0, duration=1, delays=(0, 0),
        audio_present=(False, False), audio_mode="mute", ass_paths=(None, None),
        clear_output_rotation=False,
    )
    assert "rotate=0" not in args


@pytest.mark.parametrize(
    ("angle", "filter_text"),
    [(0, "null[orient_fix0]"), (180, "hflip,vflip[orient_fix0]"),
     (90, "transpose=cclock"), (270, "transpose=clock")],
)
def test_modern_graph_normalizes_each_input_before_ass(angle, filter_text):
    args, _ = nvidia_modern.build_command(
        ffmpeg_exe="ffmpeg", video_paths=("a.mp4", "b.mp4"), output="out.mp4",
        layout="top_bottom", input_size=(3840, 2160), scale=1, dual4k=False,
        preset="balanced", bitrate_mbps=0, duration=1, delays=(0, 0),
        audio_present=(False, False), audio_mode="mute", ass_paths=("a.ass", "b.ass"),
        orientation_filters=(inspect_orientation(_stream(angle))["filter"], ""),
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "-noautorotate" in args
    assert "scale_cuda" in graph and "hwdownload,format=nv12" in graph
    assert "[orient_fix0]" in graph
    if filter_text != "null[orient_fix0]":
        assert filter_text in graph
    assert graph.index("[orient_fix0]") < graph.index("ass=filename") < graph.index("tpad=")
    assert "hevc_nvenc" in args and "rotate=0" in args


class _Provider:
    def __init__(self, filename):
        self.filename = filename

    def generate_ass(self, *_args, **_kwargs):
        return "[Script Info]\n"


def test_shared_legacy_graph_has_independent_orientation_before_ass(monkeypatch, tmp_path):
    payload_by_file = {
        "one.mp4": {"format": {"duration": "1"}, "streams": [_stream(90)]},
        "two.mp4": {"format": {"duration": "1"}, "streams": [_stream(270)]},
    }

    def probe(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(payload_by_file[command[-1]]), "")

    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(export_prepare.subprocess, "run", probe)
    monkeypatch.setattr(export_prepare, "probe_legacy_encoder", lambda *_args: True)
    monkeypatch.setattr(export_prepare, "probe_encoder_limit", lambda *_args: (3840, 2160))
    opts = {
        "playback_speed": 1, "dual_4k": False, "hw": "CPU", "backend": 2,
        "preset": "Balanced", "output": str(tmp_path / "out.mp4"), "layout": "top_bottom",
        "offset": 0, "bitrate": 0, "audio": "mute", "overlay": True,
    }
    result = export_prepare.prepare_export(opts, [_Provider("one.mp4"), _Provider("two.mp4")], tmp_path)
    args = result[2]
    graph = args[args.index("-filter_complex") + 1]
    assert "-noautorotate" in args
    parts = graph.split(";")
    assert "transpose=cclock" in parts[0]
    assert "[orient_fix0]" in parts[0] and "ass=filename" in parts[1] and "tpad=" in parts[1]
    assert "transpose=clock" in parts[2]
    assert "[orient_fix1]" in parts[2] and "ass=filename" in parts[3] and "tpad=" in parts[3]
    assert args[args.index("-metadata:s:v:0") + 1] == "rotate=0"
