import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSize, Qt, QObject
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QVideoFrame,QVideoFrameFormat
from player_widget import PlayerWidget

class PlayerOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.player=PlayerWidget(overlay_index=2)
        self.player.resize(1240,330);self.player.show();self.app.processEvents()
        # Only establishes video aspect ratio, without parsing or opening media.
        frame=QVideoFrame(QVideoFrameFormat(QSize(1920,1080),QVideoFrameFormat.Format_YUV420P))
        self.player.video_widget.videoSink().setVideoFrame(frame);QTest.qWait(100);self.app.processEvents()
    def tearDown(self):
        self.player.close();self.player.deleteLater();self.app.processEvents()
    def test_actual_video_rect_accounts_for_pillarbox(self):
        rect=self.player.actual_video_rect
        self.assertAlmostEqual(rect.width(),330*16/9,delta=1)
        self.assertAlmostEqual(rect.height(),330,delta=1)
        self.assertAlmostEqual(rect.x(),(1240-330*16/9)/2,delta=1)
        self.player.set_overlay('CAMERA\n2026-10-06\nTIME : 5.570s\nISO  : 100\nEXP  : 1/50')
        self.assertGreater(self.player.overlay_rect.x(),rect.x())
        self.assertTrue(rect.contains(self.player.overlay_rect))
    def test_time_updates_do_not_rebuild_video_layout(self):
        before=self.player.layout_update_count
        for i in range(100):self.player.set_overlay(f'TIME : {i/5:.3f}s')
        self.app.processEvents()
        self.assertEqual(self.player.layout_update_count,before)
        self.assertEqual(self.player.overlay_text_update_count,100)
        self.assertEqual(self.player.overlay_raise_count,0)
    def test_identical_text_is_cached_and_empty_text_hides(self):
        self.player.set_overlay('CAMERA')
        for _ in range(10):self.player.set_overlay('CAMERA')
        self.assertEqual(self.player.overlay_text_update_count,1)
        self.assertTrue(self.player.overlay.isVisible())
        self.player.set_overlay('')
        self.assertFalse(self.player.overlay.isVisible())
    def test_overlay_is_in_same_scene_above_video_and_ignores_mouse(self):
        self.player.set_overlay('TEST OVERLAY')
        self.assertIs(self.player.overlay.parentItem(),self.player._scene)
        self.assertEqual(self.player.overlay.z(),1)
        self.assertEqual(self.player.overlay.acceptedMouseButtons(),Qt.NoButton)
        self.assertFalse(self.player.video_widget.testAttribute(Qt.WA_NativeWindow))
        # Telemetry has no background box (Item, no color fill) and white text with black outline
        self.assertIsNone(self.player.overlay.property('color'))
        text_item = self.player._scene.findChild(QObject, 'telemetryText')
        self.assertEqual(text_item.property('color').name(), '#ffffff')
        self.assertEqual(text_item.property('styleColor').name(), '#000000')
if __name__=='__main__':unittest.main()
