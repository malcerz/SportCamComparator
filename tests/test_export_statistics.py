import json
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QProcess, QSettings
from main import MainWindow
from i18n import I18n


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_build_nuitka_disables_console_mode():
    """Verify build_nuitka.ps1 explicitly specifies --windows-console-mode=disable."""
    script_path = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "build_nuitka.ps1"
    content = script_path.read_text(encoding="utf-8")
    assert "--windows-console-mode=disable" in content


def test_windows_subprocess_no_window_flag():
    """Verify subprocess creation in main.py automatically includes CREATE_NO_WINDOW on Windows."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")
    
    import _winapi
    orig_cp = _winapi.CreateProcess
    flags_seen = []
    
    def spy_cp(*args):
        flags_seen.append(args[5])
        return orig_cp(*args)
        
    with patch.object(_winapi, "CreateProcess", spy_cp):
        res = subprocess.run(["cmd.exe", "/c", "echo test"], capture_output=True, text=True)
        assert res.returncode == 0
        assert len(flags_seen) > 0
        assert flags_seen[0] & subprocess.CREATE_NO_WINDOW != 0


def test_export_stats_history_recording_and_formatting(qapp):
    """Verify recording and formatting of stats for nVidia, AMD, Intel, and CPU."""
    I18n.init()
    w = MainWindow()
    
    # Clear test settings
    settings = QSettings("Comparator", "Comparator")
    settings.remove("export_stats_history")
    
    # 1. Record NVIDIA export
    s1 = w._save_export_stat(
        device_key="nVidia",
        device_label="nV (NVIDIA)",
        codec="HEVC",
        backend_info="D3D11 Zero-Copy (NVIDIA)",
        fps=64.5,
        duration=12.4,
        frames=800
    )
    assert "nVidia_HEVC" in s1
    assert s1["nVidia_HEVC"]["fps"] == 64.5
    assert s1["nVidia_HEVC"]["duration"] == 12.4
    
    summary1 = w._format_export_stats_summary(s1)
    assert "nV (NVIDIA)" in summary1
    assert "64.5 fps" in summary1
    assert "12.40s" in summary1
    
    # 2. Record AMD export
    s2 = w._save_export_stat(
        device_key="AMD",
        device_label="AMD",
        codec="HEVC",
        backend_info="Legacy FFmpeg (hevc_amf)",
        fps=58.2,
        duration=13.7,
        frames=800
    )
    assert "AMD_HEVC" in s2
    summary2 = w._format_export_stats_summary(s2)
    assert "nV (NVIDIA)" in summary2
    assert "AMD" in summary2
    assert "58.2 fps" in summary2
    assert "13.70s" in summary2
    
    # 3. Record Intel export
    s3 = w._save_export_stat(
        device_key="Intel",
        device_label="Intel",
        codec="HEVC",
        backend_info="Legacy FFmpeg (hevc_qsv)",
        fps=45.0,
        duration=17.8,
        frames=800
    )
    assert "Intel_HEVC" in s3
    summary3 = w._format_export_stats_summary(s3)
    assert "Intel" in summary3
    assert "45.0 fps" in summary3
    assert "17.80s" in summary3
    
    # 4. Record CPU export
    s4 = w._save_export_stat(
        device_key="CPU",
        device_label="CPU",
        codec="HEVC",
        backend_info="CPU (libx265)",
        fps=12.0,
        duration=66.7,
        frames=800
    )
    assert "CPU_HEVC" in s4
    summary4 = w._format_export_stats_summary(s4)
    assert "CPU" in summary4
    assert "12.0 fps" in summary4
    assert "66.70s" in summary4
    
    # Verify ordering: nVidia, AMD, Intel, CPU
    lines = summary4.strip().splitlines()
    assert len(lines) == 4
    assert "nV (NVIDIA)" in lines[0]
    assert "AMD" in lines[1]
    assert "Intel" in lines[2]
    assert "CPU" in lines[3]
    
    w.close()
    w.deleteLater()


def test_export_finished_dialog_shows_complete_stats(qapp):
    """Verify dialog displayed on export completion contains all statistics."""
    I18n.init()
    w = MainWindow()
    w.encoder_combo.clear()
    w.encoder_combo.addItem("NVIDIA")
    w.encoder_combo.setCurrentIndex(0)
    
    w._export_out_path = "D:/test_out.mp4"
    w._active_backend = "legacy"
    w._backend_selected = "NVIDIA_MODERN_FFMPEG"
    w._last_export_frame = 900
    w._last_export_fps = 60.0
    w._export_started_at = 100.0
    
    captured_messages = []
    def mock_info(parent, title, text):
        captured_messages.append((title, text))
        
    with patch("time.perf_counter", return_value=115.0), \
         patch.object(QMessageBox, "information", side_effect=mock_info):
        w._on_export_finished(0, QProcess.NormalExit)
        
    assert len(captured_messages) == 1
    title, text = captured_messages[0]
    
    assert I18n.tr("btn_export") == title
    assert "D:/test_out.mp4" in text
    assert "nV (NVIDIA)" in text
    assert "HEVC" in text
    assert "NVIDIA Modern FFmpeg" in text
    assert "15.00s" in text
    assert "60.0 fps" in text
    assert "900" in text
    assert "Statystyki eksportu wg urządzeń i typów kompresji" in text
    
    w.close()
    w.deleteLater()
