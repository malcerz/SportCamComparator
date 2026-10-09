import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from main import MainWindow
from options_dialog import FULL_HD, UHD_4K, OptionsDialog, comparison_output_size


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def preserve_settings():
    settings = QSettings("Comparator", "Comparator")
    saved = {key: settings.value(key) for key in settings.allKeys()}
    settings.clear(); settings.sync()
    yield
    settings.clear()
    for key, value in saved.items():
        settings.setValue(key, value)
    settings.sync()


@pytest.mark.parametrize(
    ("resolution", "layout", "expected"),
    [
        (FULL_HD, "top_bottom", (1920, 2160)),
        (FULL_HD, "left_right", (3840, 1080)),
        (UHD_4K, "top_bottom", (3840, 4320)),
        (UHD_4K, "left_right", (7680, 2160)),
    ],
)
def test_composite_dimensions(resolution, layout, expected):
    assert comparison_output_size(resolution, layout, pad_to_4k=False) == expected


def test_options_shows_padding_checkbox_and_exact_standard_canvas(app):
    dlg = OptionsDialog(resolution_available=False, resolution_reason="test encoder limit")
    assert dlg.radio_full_hd.isChecked()
    assert not dlg.radio_4k_uhd.isEnabled()
    assert dlg.chk_pad_16_9.isChecked()
    assert "3840 × 2160" in dlg.lbl_output_dimensions.text()
    dlg.chk_pad_16_9.setChecked(False)
    assert "3840 × 1080" in dlg.lbl_output_dimensions.text()
    assert "test encoder limit" in dlg.lbl_resolution_status.text()


def test_options_probe_failure_reason_is_compact_and_keeps_dimensions(app):
    from i18n import I18n

    raw_ffmpeg_error = (
        "[hevc_amf] encoder->Init() failed with error 5\n"
        "Error while opening encoder - maybe incorrect parameters\n"
        "Error sending frame to encoder: Internal bug\n"
        "Nothing was written to output file"
    )
    reason = I18n.tr("resolution_encoder_probe_failed").format(
        encoder="AMD AMF", width=7680, height=2160
    )
    dlg = OptionsDialog(resolution_available=False, resolution_reason=reason)
    assert not dlg.radio_4k_uhd.isEnabled()
    assert "7680 × 2160" in dlg.lbl_resolution_status.text()
    assert "encoder->Init()" not in dlg.lbl_resolution_status.text()
    assert len(dlg.lbl_resolution_status.text()) < len(raw_ffmpeg_error)


@pytest.mark.parametrize("layout,raw", [("top_bottom", (1920, 2160)), ("left_right", (3840, 1080))])
def test_full_hd_padding_canvas_matches_layout(app, layout, raw):
    dlg = OptionsDialog(layout=layout, resolution_available=False)
    assert comparison_output_size(FULL_HD, layout, True) == (3840, 2160)
    assert comparison_output_size(FULL_HD, layout, False) == raw
    assert "3840 × 2160" in dlg.lbl_output_dimensions.text()
    dlg.chk_pad_16_9.setChecked(False)
    assert f"{raw[0]} × {raw[1]}" in dlg.lbl_output_dimensions.text()


@pytest.mark.parametrize("layout,raw", [("top_bottom", (3840, 4320)), ("left_right", (7680, 2160))])
def test_dual4k_padding_canvas_and_availability_are_exact(app, layout, raw):
    dlg = OptionsDialog(
        active_resolution=UHD_4K, resolution_available=True, layout=layout,
        resolution_availability_by_padding={False: True, True: False},
        resolution_reason="8K probe failed",
    )
    assert comparison_output_size(UHD_4K, layout, True) == (7680, 4320)
    assert comparison_output_size(UHD_4K, layout, False) == raw
    assert dlg.selected_resolution == FULL_HD
    dlg.chk_pad_16_9.setChecked(False)
    dlg.radio_4k_uhd.setChecked(True)
    assert dlg.selected_resolution == UHD_4K
    assert f"{raw[0]} × {raw[1]}" in dlg.lbl_output_dimensions.text()


def test_ok_persists_resolution_and_cancel_does_not(app):
    dlg = OptionsDialog(resolution_available=True)
    applied = []
    dlg.comparisonResolutionApplied.connect(applied.append)
    dlg.radio_4k_uhd.setChecked(True)
    dlg._on_accept()
    assert applied == [UHD_4K]
    assert OptionsDialog.load_settings()["comparison_resolution"] == UHD_4K
    cancel = OptionsDialog(resolution_available=True)
    cancel.radio_full_hd.setChecked(True)
    cancel.radio_4k_uhd.setChecked(True)
    cancel._on_reject()
    assert OptionsDialog.load_settings()["comparison_resolution"] == UHD_4K


def test_settings_migrate_resolution_but_ignore_old_scale_values(app):
    settings = QSettings("Comparator", "Comparator")
    settings.setValue("comparison_resolution", "4k_uhd")
    settings.setValue("scale", "x0.25")
    settings.remove("playback_speed")
    loaded = OptionsDialog.load_settings()
    assert loaded["comparison_resolution"] == UHD_4K
    assert loaded["playback_speed"] == 1
    settings.setValue("playback_speed", 4)
    assert OptionsDialog.load_settings()["playback_speed"] == 4


def test_ntfy_preferences_and_unsafe_preview_scaling_preference_are_removed(app):
    settings = QSettings("Comparator", "Comparator")
    settings.setValue("ntfy_enabled", True)
    settings.setValue("ntfy_server", "https://ntfy.sh")
    settings.setValue("ntfy_topic", "test-topic")
    settings.setValue("preview_scaling_mode", "stretch")
    loaded = OptionsDialog.load_settings()
    assert "ntfy_enabled" not in loaded
    assert "ntfy_server" not in loaded
    assert "ntfy_topic" not in loaded
    assert "preview_scaling_mode" not in loaded
    assert not any(settings.contains(key) for key in ("ntfy_enabled", "ntfy_server", "ntfy_topic"))
    assert not settings.contains("preview_scaling_mode")


def test_preview_dialog_has_only_aspect_preserving_behavior(app):
    dialog = OptionsDialog(resolution_available=True)
    assert dialog.chk_export_preview.isChecked()
    assert not hasattr(dialog, "cmb_preview_scaling")


def test_resizing_live_preview_does_not_reopen_transport(app):
    window = MainWindow()
    try:
        window.enter_export_preview_mode()
        port = window.export_preview.preview_port
        window.export_preview.resize(400, 300)
        app.processEvents()
        window.export_preview.resize(800, 500)
        app.processEvents()
        assert window.export_preview.tcp_server.isListening()
        assert window.export_preview.preview_port == port
        window.exit_export_preview_mode()
    finally:
        window.close(); window.deleteLater(); app.processEvents()


def test_main_speed_control_is_independent_of_resolution(app):
    window = MainWindow()
    try:
        assert [window.scale_combo.itemData(i) for i in range(3)] == [1, 2, 4]
        window._nvidia_dual4k_supported = True
        window._dual4k_support_by_padding[True] = True
        window._on_comparison_resolution_applied(UHD_4K)
        window.scale_combo.setCurrentIndex(window.scale_combo.findData(4))
        assert window.options_data["comparison_resolution"] == UHD_4K
        assert OptionsDialog.load_settings()["playback_speed"] == 4
        window._on_comparison_resolution_applied(FULL_HD)
        assert window.scale_combo.currentData() == 4
    finally:
        window.close(); window.deleteLater(); app.processEvents()


def test_probe_result_controls_options_availability(app):
    window = MainWindow()
    try:
        window._nvidia_probe_generation = 1
        window._nvidia_probe_queue.put((1, False, "no modern", {False: (False, "not tested"), True: (True, "size pass")}, ""))
        window._poll_nvidia_export_modes()
        assert window._nvidia_dual4k_supported
        dlg = OptionsDialog(resolution_available=True)
        assert dlg.radio_4k_uhd.isEnabled()
    finally:
        window.close(); window.deleteLater(); app.processEvents()
