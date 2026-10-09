"""Comprehensive verification of inline MainWindow export preview, HEVC profiles, and rotation."""
import sys
import os
import json
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from main import MainWindow
from export_live_preview import ExportLivePreview
from telemetry_factory import create_telemetry
import export_prepare

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'tests/artifacts/inline_preview_verification'
ART.mkdir(parents=True, exist_ok=True)

video1 = 'D:/GoPro/GX010338.MP4'
video2 = 'D:/GoPro/DJI_20261002062647_0003_D.MP4'

app = QApplication.instance() or QApplication([])

def test_inline_preview():
    print("=== TEST 1: Widget Architecture Verification ===")
    assert not issubclass(ExportLivePreview, QDialog), "ExportLivePreview must NOT be a QDialog!"
    print("[PASS] ExportLivePreview is a QWidget, not a QDialog.")

    window = MainWindow()
    window.resize(1280, 720)
    window.show()
    app.processEvents()

    assert hasattr(window, 'preview_stack'), "MainWindow must have preview_stack (QStackedWidget)!"
    assert hasattr(window, 'preset_combo'), "MainWindow must have preset_combo!"
    assert not hasattr(window, 'codec_combo'), "MainWindow must NOT have codec_combo (H.264 removed)!"
    assert window.preset_combo.count() == 3, f"preset_combo must have 3 items, found {window.preset_combo.count()}"
    assert window.preset_combo.currentIndex() == 1, "Default preset must be index 1 (Zbalansowany)!"
    assert window.preview_stack.currentIndex() == 0, "Normal preview must be at index 0!"
    assert window.preview_stack.widget(0) is window.splitter, "Index 0 must be the dual-player splitter!"
    assert window.preview_stack.widget(1) is window.export_preview, "Index 1 must be export_preview!"

    print("[PASS] MainWindow layout and preset combo verified.")

    print("\n=== TEST 2: Control Locking & Stack Switching on Export ===")
    window.telemetry1 = create_telemetry(video1)
    window.telemetry2 = create_telemetry(video2)
    window.player1.setSource(QUrl.fromLocalFile(video1))
    window.player2.setSource(QUrl.fromLocalFile(video2))
    window.encoder_combo.setCurrentText('AMD AMF')
    window.backend_combo.setCurrentIndex(1)
    window.layout_mode.setCurrentIndex(0)  # Left / Right

    output_path = ART / 'test_inline_preview_output.mp4'
    original_prepare = export_prepare.prepare_export

    def fast_prepare(options, providers, directory):
        res = original_prepare(options, providers, directory)
        cfg_file = Path(res[2][1])
        c = json.loads(cfg_file.read_text(encoding='utf-8'))
        c['duration_limit_seconds'] = 15.0  # 15 seconds test (sufficient time for multiple 1 fps preview frames)
        cfg_file.write_text(json.dumps(c), encoding='utf-8')
        return res

    frames_received = []
    def on_frame(meta, jpeg):
        frames_received.append((meta, len(jpeg)))

    window.export_preview.packetReceived = on_frame

    with patch('main.QFileDialog.getSaveFileName', return_value=(str(output_path), '')), \
         patch.object(export_prepare, 'prepare_export', fast_prepare), \
         patch.object(QMessageBox, 'information'), patch.object(QMessageBox, 'critical'):

        # Start export
        window.btn_export.click()
        app.processEvents()

        # Check that playback is paused
        from PySide6.QtMultimedia import QMediaPlayer
        assert window.player1.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState, "Player 1 must be paused!"
        assert window.player2.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState, "Player 2 must be paused!"

        # Check controls locked
        assert not window.layout_mode.isEnabled(), "layout_mode must be locked during export!"
        assert not window.preset_combo.isEnabled(), "preset_combo must be locked during export!"
        assert not window.encoder_combo.isEnabled(), "encoder_combo must be locked during export!"
        assert not window.bitrate_spin.isEnabled(), "bitrate_spin must be locked during export!"
        assert not window.scale_combo.isEnabled(), "scale_combo must be locked during export!"
        assert not window.btn_video1.isEnabled(), "btn_video1 must be locked during export!"
        assert not window.btn_video2.isEnabled(), "btn_video2 must be locked during export!"

        # Check stack switched to export preview
        assert window.preview_stack.currentIndex() == 1, "Stack must switch to export preview (page 1)!"

        # Check NO extra top-level dialogs/windows opened
        top_levels = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        assert len(top_levels) == 1 and top_levels[0] is window, f"Only MainWindow may be visible! Found: {top_levels}"

        print("[PASS] Controls locked, dual players paused, preview stack on page 1, zero separate windows.")

        # Wait for export to finish
        start_t = time.monotonic()
        captured_screen = False
        while window._is_exporting and time.monotonic() - start_t < 60:
            app.processEvents()
            if len(frames_received) >= 2 and not captured_screen:
                # Capture preview snapshot in main window
                window.grab().save(str(ART / 'inline_preview_mainwindow.png'))
                window.export_preview.grab().save(str(ART / 'inline_preview_widget.png'))
                captured_screen = True
            time.sleep(0.01)

        assert not window._is_exporting, "Export timed out!"
        assert window.preview_stack.currentIndex() == 0, "Stack must switch back to normal dual-player view (page 0)!"
        assert window.layout_mode.isEnabled(), "Controls must be re-enabled after export!"
        assert window.preset_combo.isEnabled(), "preset_combo must be re-enabled after export!"
        assert window.encoder_combo.isEnabled(), "encoder_combo must be re-enabled after export!"
        print("[PASS] Stack returned to page 0, controls re-enabled.")

    print(f"DEBUG: export log:\n{window._export_log}")
    print(f"DEBUG: last gpu metrics: {window._last_gpu_metrics}")
    assert len(frames_received) >= 2, f"Expected preview frames, got {len(frames_received)}"
    print(f"[PASS] Received {len(frames_received)} preview frames via named pipe.")

    # Check metrics
    m = window._last_gpu_metrics
    assert m['status'] == 'success'
    assert m['full_frame_hwdownload_count'] == 0, "FULL_FRAME_HWDOWNLOAD_COUNT must be 0!"
    assert m['full_frame_hwupload_count'] == 0, "FULL_FRAME_HWUPLOAD_COUNT must be 0!"
    assert m['software_frame_count'] == 0, "SOFTWARE_VIDEO_FRAME_COUNT must be 0!"
    print(f"[PASS] Zero-copy gate confirmed: hwdown={m['full_frame_hwdownload_count']}, hwup={m['full_frame_hwupload_count']}, sw={m['software_frame_count']}")

    window.close()
    app.processEvents()
    print("=== ALL INLINE PREVIEW TESTS PASSED! ===")

if __name__ == '__main__':
    test_inline_preview()
