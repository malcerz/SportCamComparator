"""Unit test matrix for universal capability-based export backends."""
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure src/ is on sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import video_encoder
import export_prepare


@pytest.fixture(autouse=True)
def _legacy_hierarchy_tests_disable_nvidia_modern(monkeypatch):
    """These historical matrix cases specifically exercise the pre-Modern fallback tree."""
    monkeypatch.setattr(
        export_prepare.nvidia_modern,
        "probe_nvidia_modern",
        lambda *_args, **_kwargs: (False, "Modern intentionally disabled by this test fixture"),
    )
    # A clean source checkout does not contain the locally built native EXE.
    # Use a sentinel path here; individual tests mock the capability probe and
    # exercise backend selection without requiring a compiled helper.
    monkeypatch.setattr(
        export_prepare,
        "resolve_export_helper",
        lambda backend, encoder: (Path(__file__).resolve(), None)
        if str(backend).lower() == "d3d11" and str(encoder).lower() not in ("cpu", "libx265", "none")
        else (None, None),
    )


class DummyProvider:
    def __init__(self, filename="dummy.mp4", camera="GoPro", duration=10.0):
        self.filename = filename
        self.camera_name = camera
        self.duration = duration
        self.samples = []

    def get_datetime_at(self, idx):
        return None

    def generate_ass(self, duration):
        return ""


@pytest.fixture
def dummy_providers(tmp_path):
    f1 = tmp_path / "v1.mp4"
    f2 = tmp_path / "v2.mp4"
    f1.write_bytes(b"\x00" * 100)
    f2.write_bytes(b"\x00" * 100)
    return DummyProvider(str(f1)), DummyProvider(str(f2))


def test_helper_resolution_never_uses_cwd(tmp_path, monkeypatch):
    """Verify resolve_export_helper never relies on current working directory."""
    app_root = tmp_path / "application"
    bin_dir = app_root / "bin"
    bin_dir.mkdir(parents=True)
    helper_file = bin_dir / "KomparatorGpuExporter.exe"
    helper_file.write_bytes(b"test helper placeholder")
    monkeypatch.setattr(video_encoder, "get_app_root", lambda: app_root)
    original_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))  # change to temp dir where bin/ does not exist
        helper, err = video_encoder.resolve_export_helper("d3d11", "AMD AMF")
        assert helper is not None
        assert helper.is_absolute()
        assert helper.name == "KomparatorGpuExporter.exe"
        assert helper.is_file()

        # CPU returns None, None
        cpu_helper, cpu_err = video_encoder.resolve_export_helper("legacy", "CPU")
        assert cpu_helper is None
        assert cpu_err is None
    finally:
        os.chdir(original_cwd)


def test_resolve_legacy_ffmpeg():
    """Verify resolve_legacy_ffmpeg resolves properly for both NVIDIA and common."""
    common_ffmpeg = video_encoder.resolve_legacy_ffmpeg("CPU")
    assert common_ffmpeg
    assert Path(common_ffmpeg).is_file() or common_ffmpeg == "ffmpeg"

    nvidia_ffmpeg = video_encoder.resolve_legacy_ffmpeg("NVIDIA")
    assert nvidia_ffmpeg
    assert Path(nvidia_ffmpeg).is_file() or nvidia_ffmpeg == "ffmpeg"


# =============================================================================
# Capability Decision Matrix (Requirement 43)
# =============================================================================

def test_matrix_cpu_only(dummy_providers, tmp_path):
    """CPU requested -> goes directly to libx265, zero GPU probes."""
    options = {
        'hw': 'CPU',
        'backend': 0,  # AUTO
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 10.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_legacy_encoder", return_value=True):
            backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
            assert backend_mode == 'legacy'
            assert '-c:v' in args
            idx = args.index('-c:v')
            assert args[idx + 1] == 'libx265'
            assert selected == 'CPU_X265'


def test_matrix_amd_d3d11_pass(dummy_providers, tmp_path):
    """AMD D3D11 PASS -> uses D3D11 Zero-Copy."""
    options = {
        'hw': 'AMD AMF',
        'backend': 0,  # AUTO
        'preset': 'Najszybszy',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(True, "OK", {"status": "ok"})):
            backend_mode, helper, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
            assert backend_mode == 'd3d11'
            assert selected == 'AMD_AMF_D3D11'


def test_matrix_amd_d3d11_fail_legacy_pass(dummy_providers, tmp_path):
    """AMD D3D11 FAIL + Legacy PASS -> falls back to Legacy hevc_amf."""
    options = {
        'hw': 'AMD AMF',
        'backend': 0,  # AUTO
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "AMF fail", {"reason": "AMF_ENCODER_OPEN_FAILED"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "hevc_amf"):
                with patch.object(video_encoder, "probe_encoder_limit", return_value=(3840, 2160)):
                    backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                    assert backend_mode == 'legacy'
                    idx = args.index('-c:v')
                    assert args[idx + 1] == 'hevc_amf'
                    assert selected == 'AMD_AMF_LEGACY'


def test_matrix_amd_all_fail_cpu_pass(dummy_providers, tmp_path):
    """AMD all GPU FAIL + CPU PASS -> falls back to CPU libx265."""
    options = {
        'hw': 'AMD AMF',
        'backend': 0,  # AUTO
        'preset': 'Najlepsza jakość',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "AMF fail", {"reason": "AMF_FAIL"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "libx265"):
                backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                assert backend_mode == 'legacy'
                idx = args.index('-c:v')
                assert args[idx + 1] == 'libx265'
                assert selected == 'CPU_X265'


def test_matrix_intel_d3d11_pass(dummy_providers, tmp_path):
    """Intel D3D11 PASS -> uses D3D11 Zero-Copy."""
    options = {
        'hw': 'Intel QSV',
        'backend': 0,  # AUTO
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(True, "OK", {"status": "ok"})):
            backend_mode, helper, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
            assert backend_mode == 'd3d11'
            assert selected == 'INTEL_QSV_D3D11'


def test_matrix_intel_d3d11_fail_legacy_pass(dummy_providers, tmp_path):
    """Intel D3D11 FAIL (QSV_PIXFMT_INTEROP_FAILED) + Legacy PASS -> uses Legacy hevc_qsv."""
    options = {
        'hw': 'Intel QSV',
        'backend': 0,  # AUTO
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "interop fail", {"reason": "QSV_PIXFMT_INTEROP_FAILED"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "hevc_qsv"):
                with patch.object(video_encoder, "probe_encoder_limit", return_value=(3840, 2160)):
                    backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                    assert backend_mode == 'legacy'
                    idx = args.index('-c:v')
                    assert args[idx + 1] == 'hevc_qsv'
                    assert selected == 'INTEL_QSV_LEGACY'


def test_matrix_intel_all_fail_cpu_pass(dummy_providers, tmp_path):
    """Intel all GPU FAIL + CPU PASS -> falls back to CPU libx265."""
    options = {
        'hw': 'Intel QSV',
        'backend': 0,
        'preset': 'Najszybszy',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "fail", {"reason": "FAIL"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "libx265"):
                backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                assert backend_mode == 'legacy'
                idx = args.index('-c:v')
                assert args[idx + 1] == 'libx265'
                assert selected == 'CPU_X265'


def test_matrix_nvidia_d3d11_pass(dummy_providers, tmp_path):
    """NVIDIA D3D11 PASS -> uses D3D11 Zero-Copy."""
    options = {
        'hw': 'NVIDIA',
        'backend': 0,
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(True, "OK", {"status": "ok"})):
            backend_mode, helper, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
            assert backend_mode == 'd3d11'
            assert selected == 'NVIDIA_D3D11'


def test_matrix_nvidia_api_mismatch_legacy_compat_pass(dummy_providers, tmp_path):
    """NVIDIA API mismatch on D3D11 + Legacy compat PASS -> uses Legacy hevc_nvenc."""
    options = {
        'hw': 'NVIDIA',
        'backend': 0,
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "mismatch", {"reason": "NVENC_API_MISMATCH"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "hevc_nvenc"):
                with patch.object(video_encoder, "probe_encoder_limit", return_value=(3840, 2160)):
                    backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                    assert backend_mode == 'legacy'
                    idx = args.index('-c:v')
                    assert args[idx + 1] == 'hevc_nvenc'
                    assert selected == 'NVIDIA_LEGACY'


def test_matrix_nvidia_all_fail_cpu_pass(dummy_providers, tmp_path):
    """NVIDIA all GPU fail + CPU PASS -> falls back to CPU libx265."""
    options = {
        'hw': 'NVIDIA',
        'backend': 0,
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "fail", {"reason": "FAIL"})):
            with patch.object(video_encoder, "probe_legacy_encoder", side_effect=lambda enc, *a: enc == "libx265"):
                backend_mode, exe, args, dur, selected = export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
                assert backend_mode == 'legacy'
                idx = args.index('-c:v')
                assert args[idx + 1] == 'libx265'
                assert selected == 'CPU_X265'


def test_forced_d3d11_fails_cleanly_without_silent_fallback(dummy_providers, tmp_path):
    """Forced D3D11 must raise informative RuntimeError when D3D11 fails, no silent fallback."""
    options = {
        'hw': 'Intel QSV',
        'backend': 1,  # Forced D3D11
        'preset': 'Zbalansowany',
        'scale': 1.0,
        'offset': 0,
        'audio': 'mute',
        'layout': 'left_right',
        'output': str(tmp_path / "out.mp4"),
        'overlay': False,
        'bitrate': 20.0,
    }
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
        with patch.object(video_encoder, "probe_gpu_exporter", return_value=(False, "QSV interop failed", {"reason": "QSV_PIXFMT_INTEROP_FAILED"})):
            with pytest.raises(RuntimeError) as exc_info:
                export_prepare.prepare_export(options, dummy_providers, str(tmp_path))
            assert "QSV_PIXFMT_INTEROP_FAILED" in str(exc_info.value)


# =============================================================================
# Live Hardware Probes (host Intel / NVIDIA capability verification)
# =============================================================================

def _has_video_adapter(vendor: str) -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=5,
        )
        return vendor.lower() in result.stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return False

def test_live_hardware_probe_qsv():
    """Verify live QSV probe succeeds when Intel GPU is present."""
    if not _has_video_adapter("Intel"):
        pytest.skip("No Intel GPU is installed on this test runner")
    ok, msg, data = video_encoder.probe_gpu_exporter("qsv")
    if not ok and data.get("reason") in ("NO_ADAPTER_FOUND", "ENCODER_NOT_FOUND"):
        pytest.skip("No Intel QSV GPU on this test runner")
    assert ok is True
    assert data.get("status") == "ok"
    assert data.get("encoder") == "hevc_qsv"
    assert data.get("d3d11") is True
    assert data.get("hardware_frames") is True


def test_live_hardware_probe_nvenc():
    """Verify live NVENC probe succeeds when NVIDIA GPU is present."""
    if not _has_video_adapter("NVIDIA"):
        pytest.skip("No NVIDIA GPU is installed on this test runner")
    ok, msg, data = video_encoder.probe_gpu_exporter("nvenc")
    if not ok and data.get("reason") in ("NO_ADAPTER_FOUND", "ENCODER_NOT_FOUND"):
        pytest.skip("No NVIDIA GPU on this test runner")
    assert ok is True
    assert data.get("status") == "ok"
    assert data.get("encoder") == "hevc_nvenc"
    assert data.get("d3d11") is True
    assert data.get("hardware_frames") is True


@pytest.mark.parametrize("preset", ["speed", "balanced", "quality"])
def test_live_profiles_qsv_and_nvenc(preset):
    """Verify all 3 GUI presets pass probe for each available QSV/NVENC GPU."""
    for enc in ["qsv", "nvenc"]:
        if enc == "qsv" and not _has_video_adapter("Intel"):
            continue
        if enc == "nvenc" and not _has_video_adapter("NVIDIA"):
            continue
        ok, msg, data = video_encoder.probe_gpu_exporter(enc, preset=preset)
        if not ok and data.get("reason") in ("NO_ADAPTER_FOUND", "ENCODER_NOT_FOUND"):
            continue
        assert ok is True
        assert data.get("status") == "ok"


def test_native_gpu_exporter_overlay_pixel_contract():
    """Verify native KomparatorGpuExporter overlay has transparent background, black outline, and white glyphs."""
    import json
    import subprocess
    helper = SRC_DIR.parent / "bin" / "KomparatorGpuExporter.exe"
    if not helper.is_file():
        pytest.skip("KomparatorGpuExporter.exe not found")
    proc = subprocess.run([str(helper), "--test-overlay"], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    json_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    assert len(json_lines) > 0
    data = json.loads(json_lines[-1])
    assert data.get("status") == "ok"
    assert data.get("background_alpha_zero") is True
    assert data.get("outline_pixel") is True
    assert data.get("white_glyph_pixel") is True
    assert data.get("transparent_pixels", 0) > 0


def test_legacy_ass_style_contract():
    """Verify legacy ASS generation uses white text, black outline, no background box, and no shadow."""
    from telemetry_gpmf import GPMFTelemetry
    telemetry = GPMFTelemetry.__new__(GPMFTelemetry)
    telemetry.camera_name = "DJI Osmo Action 6"
    telemetry.start_datetime = "2026-10-06 12:00:00"
    telemetry.samples = [
        type("Sample", (), {"timestamp": 0.0, "iso": 100, "exposure": 0.01, "dt": None})()
    ]
    telemetry.timestamps = [0.0]
    ass_content = telemetry.generate_ass(duration_sec=1.0, fps=30.0)
    # Style: Telemetry,Consolas,16,&H00FFFFFF,&H000000FF,&H00000000,&HFF000000,1,0,0,0,100,100,0,0,1,2,0,7,10,10,10,1
    assert "&H00FFFFFF" in ass_content   # White fill
    assert "&H00000000" in ass_content   # Black outline
    assert "&HFF000000" in ass_content   # Transparent background box (BackColour alpha FF)
    assert ",1,2,0,7," in ass_content    # BorderStyle=1, Outline=2, Shadow=0, Alignment=7

