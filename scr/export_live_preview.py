"""Bounded, separate IPC for thumbnails of the native final compositor canvas."""
import json
import struct
import time
import uuid
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QLocalServer, QTcpServer, QTcpSocket, QHostAddress
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton


def choose_preview_size(viewport_size, composition_size):
    """Fit a sharp thumbnail to the viewport, source, and 1600x900 limits."""
    viewport_width = max(2, int(viewport_size.width()))
    viewport_height = max(2, int(viewport_size.height()))
    source_width, source_height = map(int, composition_size)
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Composition dimensions must be positive")
    scale = min(
        viewport_width / source_width,
        viewport_height / source_height,
        1600 / source_width,
        900 / source_height,
        1.0,
    )
    return (max(2, int(source_width * scale) // 2 * 2),
            max(2, int(source_height * scale) // 2 * 2))


class ExportLivePreview(QWidget):
    MAX_JPEG = 8 * 1024 * 1024
    MAX_PACKET = MAX_JPEG
    MAX_STREAM_BUFFER = 10 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QLabel('Oczekiwanie na pierwszą klatkę…')
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(160, 90)
        self.image.setStyleSheet('background: black; color: white; font-size: 14px;')
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: #ddd; font-size: 12px; padding: 2px 4px;')
        self.cancel = QPushButton('Anuluj eksport')
        self.cancel.setFixedHeight(28)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.image, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(6, 2, 6, 4)
        bottom_bar.addWidget(self.status, 1)
        bottom_bar.addWidget(self.cancel)
        layout.addLayout(bottom_bar)

        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._connect)
        self.socket = None
        self.tcp_server = QTcpServer(self)
        self.tcp_server.newConnection.connect(self._accept_tcp)
        self.tcp_socket = None
        self.tcp_buffer = bytearray()
        self.tcp_frame = 0
        self.preview_port = 0
        self.tcp_preview_failed = False
        self.preview_warning = ""
        self.buffer = bytearray()
        self.latest = None
        self.pixmap = QPixmap()
        self.last_metadata = None
        self.displayed_count = 0
        self.received_count = 0
        self.dropped_count = 0
        self.rejected_count = 0
        self.bytes_received = 0
        self.last_display_delay_ms = None
        self.total_display_delay_ms = 0.0
        self.max_display_delay_ms = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._display)
        self.packetReceived = None  # Optional verification callback; JPEG never persists in production.

    def start(self):
        self.stop()
        self.pipe_name = 'komparator-preview-' + uuid.uuid4().hex
        if not self.server.listen(self.pipe_name):
            self.status.setText('Podgląd niedostępny: ' + self.server.errorString())
            self.image.setText('Brak podglądu')
            self.pipe_name = ''
        self.tcp_server.close()
        self.tcp_buffer.clear()
        self.tcp_frame = 0
        self.tcp_preview_failed = False
        self.preview_warning = ""
        if self.tcp_server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            self.preview_port = self.tcp_server.serverPort()
        else:
            self.preview_port = 0
            self.status.setText('Podgląd FFmpeg niedostępny: nie można otworzyć lokalnego TCP.')
        self.image.setText('Oczekiwanie na pierwszą klatkę…')
        self.pixmap = QPixmap()
        self.last_metadata = None
        self.displayed_count = 0
        self.received_count = 0
        self.dropped_count = 0
        self.rejected_count = 0
        self.bytes_received = 0
        self.last_display_delay_ms = None
        self.total_display_delay_ms = 0.0
        self.max_display_delay_ms = 0.0
        self.timer.start()
        return self.pipe_name

    def _accept_tcp(self):
        """Accept the single local FFmpeg preview stream."""
        while self.tcp_server.hasPendingConnections():
            socket = self.tcp_server.nextPendingConnection()
            if self.tcp_socket:
                socket.abort()
                socket.deleteLater()
                continue
            self.tcp_socket = socket
            socket.setReadBufferSize(self.MAX_STREAM_BUFFER)
            socket.readyRead.connect(self._read_tcp)
            socket.disconnected.connect(self._tcp_disconnected)
            self._read_tcp()

    def _read_tcp(self):
        if not self.tcp_socket:
            return
        chunk = bytes(self.tcp_socket.readAll())
        self.bytes_received += len(chunk)
        self.tcp_buffer.extend(chunk)
        if len(self.tcp_buffer) > self.MAX_STREAM_BUFFER:
            # Keep only a possible SOI prefix and reject oversized/corrupt data.
            start = self.tcp_buffer.rfind(b"\xff\xd8")
            self.rejected_count += 1
            self.tcp_buffer[:] = self.tcp_buffer[start:] if start >= 0 else b""
        while True:
            start = self.tcp_buffer.find(b"\xff\xd8")
            if start < 0:
                self.tcp_buffer[:] = b"\xff" if self.tcp_buffer.endswith(b"\xff") else b""
                break
            if start:
                del self.tcp_buffer[:start]
                self.rejected_count += 1
            end = self.tcp_buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(self.tcp_buffer) > self.MAX_JPEG:
                    del self.tcp_buffer[:2]
                    self.rejected_count += 1
                    continue
                break
            jpeg = bytes(self.tcp_buffer[:end + 2])
            del self.tcp_buffer[:end + 2]
            self.tcp_frame += 1
            self.received_count += 1
            if self.latest is not None:
                self.dropped_count += 1
            self.latest = ({
                "type": "preview", "frame": self.tcp_frame,
                "pts": self.tcp_frame / 5.0, "encoding": "jpeg",
                "received_at": time.perf_counter(),
            }, jpeg)
        if self.last_metadata is None:
            self._display()

    def _tcp_disconnected(self):
        if self.tcp_buffer:
            self.rejected_count += 1
            self.tcp_buffer.clear()
        if self.tcp_socket:
            self.tcp_socket.deleteLater()
            self.tcp_socket = None

    def mark_tcp_preview_unavailable(self, message="Podgląd niedostępny; eksport wideo trwa dalej."):
        """Disable the auxiliary receiver after the secondary FFmpeg output fails."""
        if self.tcp_preview_failed:
            return
        self.tcp_preview_failed = True
        self.preview_warning = message
        self.preview_port = 0
        self.tcp_server.close()
        if self.tcp_buffer:
            self.rejected_count += 1
            self.tcp_buffer.clear()
        tcp_socket, self.tcp_socket = self.tcp_socket, None
        if tcp_socket:
            tcp_socket.abort()
            tcp_socket.deleteLater()
        self.status.setText(message)

    def _connect(self):
        socket = self.server.nextPendingConnection()
        if self.socket:
            socket.abort()
            socket.deleteLater()
            return
        self.socket = socket
        socket.setReadBufferSize(self.MAX_PACKET)
        socket.readyRead.connect(self._read)
        self._read()

    def _read(self):
        if not self.socket:
            return
        self.buffer.extend(bytes(self.socket.readAll()))
        while len(self.buffer) >= 8:
            meta_size, jpeg_size = struct.unpack_from('<II', self.buffer)
            size = 8 + meta_size + jpeg_size
            if meta_size > 4096 or jpeg_size > self.MAX_PACKET or not jpeg_size:
                self.stop()
                self.status.setText('Nieprawidłowy pakiet podglądu')
                if self.pixmap.isNull():
                    self.image.setText('Brak podglądu')
                return
            if len(self.buffer) < size:
                return
            packet = bytes(self.buffer[8:size])
            del self.buffer[:size]
            try:
                metadata = json.loads(packet[:meta_size])
                if not (0 < metadata['width'] <= 1600 and 0 < metadata['height'] <= 900
                        and metadata['encoding'] == 'jpeg'):
                    raise ValueError('Invalid thumbnail dimensions')
                jpeg = packet[meta_size:]
                if len(jpeg) > self.MAX_JPEG:
                    raise ValueError('Preview frame is too large')
                if self.latest is not None:
                    self.dropped_count += 1
                metadata['received_at'] = time.perf_counter()
                self.latest = (metadata, jpeg)
                self.received_count += 1
                self.bytes_received += len(jpeg)
                if self.packetReceived:
                    self.packetReceived(metadata, jpeg)
            except (ValueError, KeyError, TypeError):
                self.stop()
                self.status.setText('Błąd danych podglądu')
                if self.pixmap.isNull():
                    self.image.setText('Brak podglądu')
                return
        if self.last_metadata is None:
            self._display()

    def _display(self):
        if self.latest:
            metadata, jpeg = self.latest
            self.latest = None
            pixmap = QPixmap()
            if pixmap.loadFromData(jpeg, 'JPEG') and pixmap.width() <= 1600 and pixmap.height() <= 900:
                self.pixmap = pixmap
                self.last_metadata = metadata
                self.displayed_count += 1
                received_at = metadata.get('received_at')
                if received_at is not None:
                    self.last_display_delay_ms = max(0.0, (time.perf_counter() - received_at) * 1000)
                    self.total_display_delay_ms += self.last_display_delay_ms
                    self.max_display_delay_ms = max(self.max_display_delay_ms, self.last_display_delay_ms)
                self._resize_image()
            else:
                self.rejected_count += 1

    def _resize_image(self):
        if not self.pixmap.isNull():
            self.image.setPixmap(self.pixmap.scaled(
                self.image.size(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_image()

    def stop(self):
        self.timer.stop()
        self.server.close()
        self.tcp_server.close()
        self.preview_port = 0
        if self.tcp_buffer:
            self.rejected_count += 1
        self.tcp_buffer.clear()
        tcp_socket, self.tcp_socket = self.tcp_socket, None
        if tcp_socket:
            tcp_socket.abort()
            tcp_socket.deleteLater()
        if self.socket:
            self.socket.abort()
            self.socket.deleteLater()
            self.socket = None
        self.buffer.clear()
        self.latest = None
