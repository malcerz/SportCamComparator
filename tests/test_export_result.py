import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from export_result import is_preview_only_failure, validate_completed_mp4


def _preview_failure_log():
    return """[vost#1:0/mjpeg] Error submitting a packet to the muxer: Error number -10054 occurred
[out#1/fifo] Error muxing a packet
frame=3000
progress=end
"""


def test_only_completed_secondary_fifo_failure_is_recoverable():
    assert is_preview_only_failure(_preview_failure_log())
    assert not is_preview_only_failure(_preview_failure_log(), cancelled=True)
    assert not is_preview_only_failure(_preview_failure_log().replace("progress=end", "progress=continue"))
    assert not is_preview_only_failure(_preview_failure_log() + "[out#0/mp4] Error writing trailer\n")
    assert not is_preview_only_failure("frame=3000\nprogress=end\n")


def _probe_result(*, duration="10.0", size=(3840, 2160), frames="300", codec="hevc"):
    return {
        "format": {"duration": duration},
        "streams": [{"codec_type": "video", "codec_name": codec,
                     "width": size[0], "height": size[1], "nb_frames": frames,
                     "avg_frame_rate": "30/1"}],
    }


def test_ffprobe_validation_checks_mp4_geometry_duration_and_frame_count(tmp_path):
    output = tmp_path / "complete.mp4"
    output.write_bytes(b"x" * 2048)
    completed = type("Probe", (), {"returncode": 0, "stdout": json.dumps(_probe_result())})()
    with patch("export_result.subprocess.run", return_value=completed):
        result = validate_completed_mp4("ffprobe", output, (3840, 2160), 10)
    assert result == {"width": 3840, "height": 2160, "duration": 10.0,
                      "codec_name": "hevc", "nb_frames": 300}


@pytest.mark.parametrize("probe", [
    _probe_result(duration="5.0"),
    _probe_result(frames="150"),
    _probe_result(size=(1920, 1080)),
    _probe_result(codec="h264"),
])
def test_ffprobe_validation_rejects_incomplete_or_wrong_mp4(tmp_path, probe):
    output = tmp_path / "invalid.mp4"
    output.write_bytes(b"x" * 2048)
    completed = type("Probe", (), {"returncode": 0, "stdout": json.dumps(probe)})()
    with patch("export_result.subprocess.run", return_value=completed):
        with pytest.raises(ValueError):
            validate_completed_mp4("ffprobe", output, (3840, 2160), 10)
