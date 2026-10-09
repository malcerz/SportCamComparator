import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import export_prepare


class Provider:
    def __init__(self, name):
        self.filename = name

    def get_datetime_at(self, _seconds):
        return None


@pytest.mark.parametrize(
    "layout,raw_size",
    [("left_right", (3840, 1080)), ("top_bottom", (1920, 2160))],
)
@pytest.mark.parametrize("pad", [False, True])
def test_d3d_config_keeps_raw_composite_geometry_for_whole_canvas_padding(
    monkeypatch, tmp_path, layout, raw_size, pad
):
    metadata = {"format": {"duration": "4"}, "streams": [
        {"codec_type": "video", "width": 3840, "height": 2160, "avg_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ]}
    monkeypatch.setattr(export_prepare, "resolve_legacy_ffprobe", lambda _hw: "ffprobe")
    monkeypatch.setattr(
        export_prepare.subprocess, "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(metadata), ""),
    )
    monkeypatch.setattr(export_prepare, "resolve_export_helper", lambda *_args: ("helper.exe", None))
    monkeypatch.setattr(export_prepare, "probe_gpu_exporter", lambda *_args: (True, "PASS"))
    options = {
        "output": str(tmp_path / "out.mp4"), "scale": 1, "hw": "NVIDIA", "backend": 1,
        "preset": "Balanced", "bitrate": 10, "audio": "mute", "layout": layout,
        "offset": 0, "overlay": False, "pad_to_16_9": pad,
    }
    mode, _program, args, _duration, _backend = export_prepare.prepare_export(
        options, (Provider("one.mp4"), Provider("two.mp4")), tmp_path
    )
    assert mode == "d3d11"
    config_path = Path(args[args.index("--config") + 1])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert (config["width"], config["height"]) == raw_size
    assert config["pad_to_4k"] is pad
