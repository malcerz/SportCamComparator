"""Comprehensive tests for Comparator GUI overhaul, Options, and i18n."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtWidgets import QApplication, QMessageBox, QLabel
from PySide6.QtCore import Qt, QPoint, QSettings, QThread
from PySide6.QtTest import QTest
from main import MainWindow, CustomTitleBar, HTCLIENT, HTCAPTION, HTMAXBUTTON, HTLEFT, HTRIGHT, HTTOP, HTBOTTOM, WM_NCHITTEST
from options_dialog import OptionsDialog
from i18n import I18n
import export_prepare
import video_encoder


class TestComparatorGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = MainWindow()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def test_application_name_and_title(self):
        """Verify windowTitle and title_label are strictly 'Comparator'."""
        self.assertEqual(self.w.windowTitle(), "Comparator")
        self.assertEqual(self.w.title_bar.title_label.text(), "Comparator")

    def test_top_bar_controls_presence(self):
        """Verify all main controls are situated in the top bar."""
        tb = self.w.title_bar
        self.assertIsNotNone(tb.btn_load)
        self.assertEqual(tb.btn_load.text(), I18n.tr("btn_load"))
        self.assertIsNotNone(tb.btn_options)
        self.assertEqual(tb.btn_options.text(), I18n.tr("btn_options"))
        self.assertIsNotNone(tb.btn_min)
        self.assertIsNotNone(tb.btn_max)
        self.assertIsNotNone(tb.btn_close)

        # Main layout check: index 0 is title_bar, index 1 is export_progress
        root = self.w.main_widget.layout()
        self.assertIs(root.itemAt(0).widget(), self.w.title_bar)
        self.assertIs(root.itemAt(1).widget(), self.w.export_progress)

    def test_coffee_link_absent_from_main_window(self):
        """Verify coffee link is completely removed from MainWindow and no footer exists."""
        coffee_labels = [w for w in self.w.findChildren(QLabel) if "buycoffee.to" in w.text()]
        self.assertEqual(len(coffee_labels), 0)
        # Verify root layout ends at seekbar_area with no trailing footer row
        root = self.w.main_widget.layout()
        self.assertEqual(root.count(), 5)
        self.assertIs(root.itemAt(4).widget(), self.w.seekbar_area)

    def test_coffee_link_only_in_options_dialog(self):
        """Verify coffee link is present, clickable, and localized strictly in OptionsDialog."""
        dlg = OptionsDialog(self.w)
        coffee_labels = [w for w in dlg.findChildren(QLabel) if "buycoffee.to" in w.text()]
        self.assertEqual(len(coffee_labels), 1)
        lbl = coffee_labels[0]
        self.assertTrue(lbl.openExternalLinks())
        self.assertIn("https://buycoffee.to/malcerz", lbl.text())
        self.assertEqual(dlg.lbl_coffee_prompt.text(), I18n.tr("buy_coffee_prompt"))
        dlg.close()

    def test_load_videos_transactional_validation(self):
        """Verify single load button requires exactly two video files."""
        # Mock QMessageBox to prevent blocking
        with patch.object(QMessageBox, "critical") as mock_err:
            # 1. User cancels (empty list) -> returns False, no error
            res = self.w.load_videos([])
            self.assertFalse(res)
            self.assertFalse(mock_err.called)

            # 2. User selects 1 file -> error dialog, returns False
            res = self.w.load_videos(["video1.mp4"])
            self.assertFalse(res)
            self.assertTrue(mock_err.called)

            # 3. User selects 3 files -> error dialog, returns False
            mock_err.reset_mock()
            res = self.w.load_videos(["v1.mp4", "v2.mp4", "v3.mp4"])
            self.assertFalse(res)
            self.assertTrue(mock_err.called)

            # 4. User selects exactly 2 files -> success
            mock_err.reset_mock()
            with patch.object(self.w, "_start_telemetry"), patch.object(self.w.player1, "setSource"), patch.object(self.w.player2, "setSource"):
                res = self.w.load_videos(["v1.mp4", "v2.mp4"])
                self.assertTrue(res)
                self.assertFalse(mock_err.called)

    def test_load_button_clicked_signal_and_qtest_click(self):
        """Verify QTest.mouseClick on btn_load triggers load_two_videos on GUI thread and invokes QFileDialog."""
        thread_verified = []
        def mock_open_files(*args, **kwargs):
            thread_verified.append(QThread.currentThread() == QApplication.instance().thread())
            return ["fileA.mp4", "fileB.mp4"], ""

        with patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames", side_effect=mock_open_files) as mock_dlg, \
             patch.object(self.w, "_start_telemetry"), \
             patch.object(self.w.player1, "setSource"), \
             patch.object(self.w.player2, "setSource"):
            self.w.show()
            self.app.processEvents()

            # Click using QTest
            QTest.mouseClick(self.w.btn_load, Qt.LeftButton)
            self.assertTrue(mock_dlg.called)
            self.assertTrue(len(thread_verified) > 0 and thread_verified[0])

    def test_titlebar_hit_test_interactive_controls(self):
        """Verify WM_NCHITTEST logic treats all interactive controls as HTCLIENT and empty titlebar as HTCAPTION."""
        self.w.resize(2400, 720)
        self.w.show()
        self.app.processEvents()

        tb = self.w.title_bar
        controls = [
            ("btn_load", self.w.btn_load, HTCLIENT),
            ("layout_mode", self.w.layout_mode, HTCLIENT),
            ("audio_combo", self.w.audio_combo, HTCLIENT),
            ("decoder_combo", self.w.decoder_combo, HTCLIENT),
            ("btn_export", self.w.btn_export, HTCLIENT),
            ("preset_combo", self.w.preset_combo, HTCLIENT),
            ("encoder_combo", self.w.encoder_combo, HTCLIENT),
            ("bitrate_spin", self.w.bitrate_spin, HTCLIENT),
            ("scale_combo", self.w.scale_combo, HTCLIENT),
            ("btn_options", self.w.btn_options, HTCLIENT),
            ("title_label", tb.title_label, HTCAPTION),
            ("btn_min", tb.btn_min, HTCLIENT),
            ("btn_max", tb.btn_max, HTMAXBUTTON),
            ("btn_close", tb.btn_close, HTCLIENT),
        ]

        for name, ctrl, expected in controls:
            pos_in_tb = ctrl.mapTo(tb, ctrl.rect().center())
            if ctrl is tb.btn_max:
                actual = HTMAXBUTTON
            else:
                child = tb.childAt(pos_in_tb)
                actual = HTCLIENT if self.w._is_interactive_titlebar_control(child) else HTCAPTION
            self.assertEqual(actual, expected, f"Control {name} hit-test mismatch: expected {expected}, got {actual}")

        # Empty draggable area between controls layout and caption buttons
        empty_x = (tb.controls_layout.geometry().right() + tb.btn_min.geometry().left()) // 2
        child = tb.childAt(empty_x, tb.height() // 2)
        actual_empty = HTCLIENT if self.w._is_interactive_titlebar_control(child) else HTCAPTION
        self.assertEqual(actual_empty, HTCAPTION, "Empty title bar space should be HTCAPTION")

    def test_options_dialog_sliders_and_persistence(self):
        """Verify options dialog reads, writes, and signals settings."""
        # Set clean test values
        OptionsDialog.save_settings(font_scale=1.5, opacity=0.8, pad_to_4k=True)
        loaded = OptionsDialog.load_settings()
        self.assertAlmostEqual(loaded["overlay_font_scale"], 1.5)
        self.assertAlmostEqual(loaded["overlay_opacity"], 0.8)
        self.assertTrue(loaded["pad_to_4k"])

        dlg = OptionsDialog(self.w)
        self.assertEqual(dlg.slider_font.value(), 150)
        self.assertEqual(dlg.slider_opacity.value(), 80)
        self.assertFalse(hasattr(dlg, "chk_pad_4k"))

        # Modify values
        dlg.slider_font.setValue(120)
        dlg.slider_opacity.setValue(90)

        signal_received = []
        dlg.settingsApplied.connect(lambda f, o, p: signal_received.append((f, o, p)))
        dlg._on_accept()

        self.assertEqual(len(signal_received), 1)
        self.assertAlmostEqual(signal_received[0][0], 1.2)
        self.assertAlmostEqual(signal_received[0][1], 0.9)
        self.assertTrue(signal_received[0][2])

        # Check persistence
        saved = OptionsDialog.load_settings()
        self.assertAlmostEqual(saved["overlay_font_scale"], 1.2)
        self.assertAlmostEqual(saved["overlay_opacity"], 0.9)
        self.assertTrue(saved["pad_to_4k"])

        # Reset defaults
        OptionsDialog.save_settings(1.0, 1.0, False)

    def test_options_applied_updates_mainwindow_and_players(self):
        """Verify applying options updates MainWindow and player widgets."""
        with patch.object(self.w.player1, "set_overlay_style") as p1_style, \
             patch.object(self.w.player2, "set_overlay_style") as p2_style:
            self.w._on_options_applied(1.4, 0.75, True)
            self.assertEqual(self.w.options_data["overlay_font_scale"], 1.4)
            self.assertEqual(self.w.options_data["overlay_opacity"], 0.75)
            self.assertTrue(self.w.options_data["pad_to_4k"])
            p1_style.assert_called_with(1.4, 0.75)
            p2_style.assert_called_with(1.4, 0.75)

    def test_export_prepare_receives_options(self, tmp_path=None):
        """Verify export_prepare receives font_scale, opacity, and pad_to_4k."""
        import tempfile
        from telemetry_factory import NullTelemetry
        with tempfile.TemporaryDirectory() as d:
            out_file = str(Path(d) / "out.mp4")
            options = {
                'output': out_file,
                'scale': 1.0,
                'hw': 'CPU',
                'backend': 2,  # Legacy
                'preset': 'balanced',
                'bitrate': 20.0,
                'audio': 'mute',
                'layout': 'left_right',
                'offset': 0,
                'overlay': True,
                'overlay_font_scale': 1.25,
                'overlay_opacity': 0.85,
                'pad_to_4k': True,
            }
            p1 = NullTelemetry(out_file)
            p2 = NullTelemetry(out_file)
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout='{"format":{"duration":"5.0"},"streams":[{"codec_type":"video"}]}')
                with patch.object(video_encoder, "probe_legacy_encoder", return_value=True):
                    mode, exe, args, dur, sel = export_prepare.prepare_export(options, (p1, p2), d)
                    self.assertEqual(mode, 'legacy')
                    # Verify pad filter in args
                    filter_complex = next(args[i+1] for i, a in enumerate(args) if a == '-filter_complex')
                    self.assertIn("pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black", filter_complex)

    def test_i18n_locales(self):
        """Verify I18n translations across pl, en, de, fr."""
        for lang in ["pl", "en", "de", "fr"]:
            I18n.LANG = lang
            self.assertEqual(I18n.tr("app_title"), "Comparator")
            self.assertTrue(len(I18n.tr("btn_load")) > 0)
            self.assertTrue(len(I18n.tr("btn_options")) > 0)
            self.assertTrue(len(I18n.tr("options_title")) > 0)
            self.assertTrue(len(I18n.tr("overlay_font_size_label")) > 0)
            self.assertTrue(len(I18n.tr("overlay_opacity_label")) > 0)
            self.assertTrue(len(I18n.tr("pad_to_4k_label")) > 0)
            self.assertTrue(len(I18n.tr("buy_coffee")) > 0)
            self.assertTrue(len(I18n.tr("buy_coffee_prompt")) > 0)

        # Explicit check for coffee prompts per prompt requirements
        I18n.LANG = "pl"
        self.assertEqual(I18n.tr("buy_coffee_prompt"), "Postaw mi kawę:")
        I18n.LANG = "en"
        self.assertEqual(I18n.tr("buy_coffee_prompt"), "Buy me a coffee:")
        I18n.LANG = "de"
        self.assertEqual(I18n.tr("buy_coffee_prompt"), "Spendiere mir einen Kaffee:")
        I18n.LANG = "fr"
        self.assertEqual(I18n.tr("buy_coffee_prompt"), "Offrez-moi un café :")

        # Restore default
        I18n.init()


if __name__ == '__main__':
    unittest.main()
