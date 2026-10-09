import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import json
import random
import struct
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QSize
from PySide6.QtNetwork import QTcpSocket, QHostAddress
from PySide6.QtGui import QImage, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from export_live_preview import ExportLivePreview


class Socket:
    def __init__(self): self.data = b''; self.aborted = False
    def readAll(self):
        data, self.data = self.data, b''
        return QByteArray(data)
    def abort(self): self.aborted = True
    def deleteLater(self): pass


class LivePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        image = QImage(960, 270, QImage.Format_RGB32)
        image.fill(QColor('red'))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'JPEG')
        cls.jpeg = bytes(buffer.data())
        large = QImage(1600, 900, QImage.Format_RGB32)
        large.fill(QColor('black'))
        painter = QPainter(large)
        rng = random.Random(17)
        for _ in range(5000):
            painter.fillRect(rng.randrange(1600), rng.randrange(900), 18, 14,
                             QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
        painter.end()
        large_buffer = QBuffer()
        large_buffer.open(QIODevice.WriteOnly)
        large.save(large_buffer, 'JPEG', 95)
        cls.large_jpeg = bytes(large_buffer.data())

    def setUp(self):
        self.preview = ExportLivePreview()
        self.preview.socket = Socket()

    def tearDown(self):
        self.preview.stop()
        self.preview.deleteLater()
        self.app.processEvents()

    def packet(self, frame=0, width=960):
        meta = json.dumps(dict(type='preview', frame=frame, pts=frame/30,
                               width=width, height=270, encoding='jpeg')).encode()
        return struct.pack('<II',len(meta),len(self.jpeg)) + meta + self.jpeg

    def feed(self,data):
        self.preview.socket.data = data
        self.preview._read()

    def test_fragmented_header_and_jpeg(self):
        packet = self.packet()
        self.feed(packet[:5])
        self.assertIsNone(self.preview.last_metadata)
        self.feed(packet[5:35])
        self.assertIsNone(self.preview.last_metadata)
        self.feed(packet[35:])
        self.assertEqual(self.preview.last_metadata['frame'],0)
        self.assertEqual(self.preview.pixmap.size().width(),960)

    def test_latest_frame_wins_preserves_whole_canvas(self):
        self.feed(self.packet(0))
        self.feed(self.packet(30) + self.packet(60))
        self.assertEqual(self.preview.last_metadata['frame'],0)
        self.preview._display()
        self.assertEqual(self.preview.last_metadata['frame'],60)
        self.preview.resize(500,350)
        self.preview.show()
        self.app.processEvents()
        self.preview._resize_image()
        self.assertAlmostEqual(self.preview.image.pixmap().width()/self.preview.image.pixmap().height(),960/270,places=1)

    def test_invalid_large_dimensions_disable_only_preview(self):
        socket=self.preview.socket
        self.feed(self.packet(width=3840))
        self.assertTrue(socket.aborted)
        self.assertIsNone(self.preview.socket)

    def test_oversized_packet_rejected_before_jpeg_decode(self):
        socket=self.preview.socket
        self.feed(struct.pack('<II',50,20*1024*1024))
        self.assertTrue(socket.aborted)
        self.assertIsNone(self.preview.socket)

    def test_stop_discards_pending_and_closes_server(self):
        self.preview.latest=({},self.jpeg)
        self.preview.buffer.extend(b'partial')
        self.preview.stop()
        self.assertFalse(self.preview.timer.isActive())
        self.assertEqual(self.preview.buffer,bytearray())
        self.assertIsNone(self.preview.latest)

    def test_preview_uses_200ms_timer_and_adapts_to_viewport(self):
        self.assertEqual(self.preview.timer.interval(), 200)
        from export_live_preview import choose_preview_size
        self.assertEqual(choose_preview_size(QSize(1600, 900), (7680, 4320)), (1600, 900))
        self.assertEqual(choose_preview_size(QSize(1000, 600), (7680, 4320)), (1000, 562))
        self.assertEqual(choose_preview_size(QSize(1200, 800), (7680, 2160)), (1200, 336))
        self.assertEqual(choose_preview_size(QSize(1973, 882), (7680, 4320)), (1568, 882))
        # Dual 4K with top/bottom fill is a 8:9 canvas; retain its composition ratio.
        self.assertEqual(choose_preview_size(QSize(1973, 882), (3840, 4320)), (784, 882))
        # A small source is never enlarged, even in a large viewport.
        self.assertEqual(choose_preview_size(QSize(4000, 2000), (1280, 720)), (1280, 720))

    def test_dynamic_jpeg_dimensions_preserve_all_layout_and_resolution_ratios(self):
        from export_live_preview import choose_preview_size
        from options_dialog import FULL_HD, UHD_4K, comparison_output_size

        viewports = (QSize(1280, 720), QSize(1024, 768), QSize(1973, 882), QSize(600, 1000))
        for resolution in (FULL_HD, UHD_4K):
            for layout in ("left_right", "top_bottom"):
                for padding in (False, True):
                    # Padding affects the export canvas only; preview dimensions
                    # come from the unpadded camera composite in either setting.
                    composition = comparison_output_size(resolution, layout, False)
                    for viewport in viewports:
                        width, height = choose_preview_size(viewport, composition)
                        self.assertEqual(width % 2, 0)
                        self.assertEqual(height % 2, 0)
                        self.assertLessEqual(width, min(1600, composition[0]))
                        self.assertLessEqual(height, min(900, composition[1]))
                        expected = composition[0] / composition[1]
                        self.assertLess(abs(width / height - expected) / expected, 0.01)

    def test_preview_preserves_circle_geometry_and_centers_full_composite(self):
        source = QImage(400, 200, QImage.Format_RGB32)
        source.fill(QColor("black"))
        painter = QPainter(source)
        painter.setPen(QColor("white"))
        painter.drawEllipse(60, 60, 80, 80)
        painter.end()
        self.preview.image.resize(200, 200)
        self.preview.pixmap = QPixmap.fromImage(source)
        self.preview._resize_image()
        fitted = self.preview.image.pixmap()
        self.assertEqual((fitted.width(), fitted.height()), (200, 100))
        self.assertAlmostEqual(fitted.width() / fitted.height(), source.width() / source.height(), places=2)

        # Measure the white circle at half scale. Equal horizontal and vertical
        # diameters prove the GUI layer has not stretched the decoded JPEG.
        image = fitted.toImage()
        rows = [x for x in range(image.width()) if image.pixelColor(x, 50).red() > 180]
        columns = [y for y in range(image.height()) if image.pixelColor(50, y).red() > 180]
        self.assertLessEqual(abs(len(rows) - len(columns)), 2)
        self.assertEqual(self.preview.image.alignment(), Qt.AlignmentFlag.AlignCenter)
        rendered = self.preview.image.grab().toImage()
        screen_rows = [x for x in range(rendered.width()) if rendered.pixelColor(x, 100).red() > 180]
        screen_columns = [y for y in range(rendered.height()) if rendered.pixelColor(100, y).red() > 180]
        self.assertLessEqual(abs(len(screen_rows) - len(screen_columns)), 2)

    def test_resize_keeps_proportions_without_reopening_preview_server(self):
        self.preview.start()
        port = self.preview.preview_port
        source = QImage(3840, 1080, QImage.Format_RGB32)
        source.fill(QColor("darkGreen"))
        self.preview.pixmap = QPixmap.fromImage(source)
        self.preview.show()
        self.preview.resize(1000, 700)
        self.app.processEvents()
        self.preview._resize_image()
        first = self.preview.image.pixmap().size()
        self.preview.resize(700, 900)
        self.app.processEvents()
        self.preview._resize_image()
        second = self.preview.image.pixmap().size()
        source_ratio = 3840 / 1080
        self.assertLess(abs(first.width() / first.height() - source_ratio) / source_ratio, 0.01)
        self.assertLess(abs(second.width() / second.height() - source_ratio) / source_ratio, 0.01)
        self.assertTrue(self.preview.tcp_server.isListening())
        self.assertEqual(self.preview.preview_port, port)

    def test_preview_image_uses_full_available_widget_width(self):
        self.preview.resize(640, 480)
        self.preview.show()
        self.app.processEvents()
        self.assertEqual(self.preview.layout().contentsMargins().left(), 0)
        self.assertEqual(self.preview.layout().contentsMargins().right(), 0)
        self.assertEqual(self.preview.image.x(), 0)
        self.assertEqual(self.preview.image.width(), self.preview.width())
        self.assertEqual(self.preview.image.y(), 0)
        self.assertTrue(self.preview.image.pixmap().isNull())

    def test_tcp_transport_reassembles_large_jpegs_and_keeps_latest(self):
        self.assertGreater(len(self.large_jpeg), 65507)
        self.preview.start()
        self.assertGreater(self.preview.preview_port, 0)
        self.preview.last_metadata = {}  # Prevent the first-frame fast path while queuing samples.
        self.preview.timer.stop()
        sender = QTcpSocket()
        sender.connectToHost(QHostAddress.LocalHost, self.preview.preview_port)
        self.assertTrue(sender.waitForConnected(1000))
        # Multiple large frames in one TCP stream exercise framing beyond UDP's
        # datagram ceiling while the GUI retains only the latest complete frame.
        sender.write(self.large_jpeg + self.large_jpeg + self.large_jpeg)
        sender.flush()
        deadline = __import__('time').monotonic() + 3
        while self.preview.tcp_frame < 3 and __import__('time').monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIsNotNone(self.preview.last_metadata)
        self.assertLessEqual(len(self.preview.tcp_buffer), self.preview.MAX_STREAM_BUFFER)
        self.assertEqual(self.preview.tcp_frame, 3)
        self.assertEqual(self.preview.received_count, 3)
        self.assertEqual(self.preview.dropped_count, 2)
        self.assertGreater(self.preview.bytes_received, 65507)
        self.preview._display()
        self.assertEqual(self.preview.displayed_count, 1)
        self.assertEqual((self.preview.pixmap.width(), self.preview.pixmap.height()), (1600, 900))
