"""GPU preview: video and telemetry share a single Qt Quick scene.

Windows QVideoWidget surface composition hid both ordinary and native QLabel
siblings in real desktop tests. VideoOutput and Text now share the same GPU
render target, with a permanent overlay z-order and no extra native windows.
"""
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QRectF, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtQuickWidgets import QQuickWidget


class PreviewSurface(QQuickWidget):
    def videoSink(self):
        return self.rootObject().property('videoSink')


class PlayerWidget(QWidget):
    def __init__(self, parent=None, *, overlay_index=1):
        super().__init__(parent)
        self.overlay_index = overlay_index
        self.overlay_text_update_count = 0
        self.overlay_raise_count = 0  # A fixed scene-graph z=1 replaces raise().
        self.layout_update_count = 0
        self._last_overlay_diagnostic = 0
        self._overlay_text = ''
        self._last_video_rect = QRectF()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video_widget = PreviewSurface(self)
        self.video_widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.video_widget.setClearColor(QColor('black'))
        self.video_widget.setSource(QUrl.fromLocalFile(str(Path(__file__).with_name('preview_video.qml'))))
        if self.video_widget.status() != QQuickWidget.Ready:
            raise RuntimeError('Preview QML: ' + '; '.join(error.toString() for error in self.video_widget.errors()))
        self._scene = self.video_widget.rootObject()
        self.overlay = self._scene.findChild(QObject, 'telemetryOverlay')
        self._scene.actualVideoRectChanged.connect(self._update_layout)
        self.player.setVideoSink(self.video_widget.videoSink())
        # Existing frame instrumentation can keep using video_item.videoSink().
        self.video_item = self.video_widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_widget)

    @property
    def actual_video_rect(self):
        return self._scene.property('actualVideoRect')

    @property
    def overlay_rect(self):
        return QRectF(self.overlay.x(), self.overlay.y(), self.overlay.width(), self.overlay.height())

    def set_overlay_style(self, font_scale: float = 1.0, opacity: float = 1.0):
        self._scene.setProperty('overlayFontScale', float(font_scale))
        self._scene.setProperty('overlayOpacity', float(opacity))

    def set_overlay(self, text):
        if text != self._overlay_text:
            self._overlay_text = text
            self.overlay_text_update_count += 1
            # Only Text/Rectangle content changes. Video geometry, font and style
            # bindings depend on contentRect, never TIME or the overlay text.
            self._scene.setProperty('overlayText', text)
        self._debug_overlay(text)

    def _debug_overlay(self, text):
        if os.getenv('KOMPARATOR_DEBUG_OVERLAY') != '1':
            return
        now = time.monotonic()
        if now - self._last_overlay_diagnostic < 1:
            return
        self._last_overlay_diagnostic = now
        print(f'PREVIEW_OVERLAY_{self.overlay_index}: {text!r} '
              f'visible={self.overlay.isVisible()} geometry={self.overlay_rect} '
              f'video_geometry={self.video_widget.geometry()} video_rect={self.actual_video_rect} '
              f'parent={self.overlay.parent()} renderer=QtQuick '
              f'native={self.video_widget.testAttribute(Qt.WA_NativeWindow)} z={self.overlay.z()}', flush=True)

    def _update_layout(self):
        rect = self.actual_video_rect
        if rect != self._last_video_rect:
            self._last_video_rect = QRectF(rect)
            self.layout_update_count += 1

    def setSource(self, source): self.player.setSource(source)
    def play(self): self.player.play()
    def pause(self): self.player.pause()
    def stop(self): self.player.stop()
    def position(self): return self.player.position()
    def set_position(self, position): self.player.setPosition(int(position))
