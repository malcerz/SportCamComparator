import os
import sys
import shutil
import subprocess
import threading
import queue
import json
import re
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Argument --hwaccel <cpu|nvidia|intel|amd> jest przekazywany przy restarcie
# przez _on_encoder_changed() i musi byc odczytany PRZED pierwszym importem
# jakiegokolwiek modulu PySide6 Multimedia, bo Qt cachuje wybor sprzetu
# statycznie przy inicjalizacji pluginu FFmpeg.
# ---------------------------------------------------------------------------
_HWACCEL_ARG_MAP = {
    "cpu":    {"QT_FFMPEG_HWACCEL": "",            "QT_FFMPEG_DECODING_HW_DEVICE_TYPES": ""},
    "nvidia": {"QT_FFMPEG_HWACCEL": "d3d11va",     "QT_FFMPEG_DECODING_HW_DEVICE_TYPES": "d3d11va,dxva2"},
    "intel":  {"QT_FFMPEG_HWACCEL": "qsv",         "QT_FFMPEG_DECODING_HW_DEVICE_TYPES": "qsv,d3d11va,dxva2"},
    "amd":    {"QT_FFMPEG_HWACCEL": "d3d11va",     "QT_FFMPEG_DECODING_HW_DEVICE_TYPES": "d3d11va,dxva2"},
}

def _apply_hwaccel_from_argv():
    """Odczytaj --hwaccel <klucz> z argv i ustaw zmienne srodowiskowe.
    Zwraca klucz jesli znaleziono, None w przeciwnym razie."""
    try:
        idx = sys.argv.index("--hwaccel")
        key = sys.argv[idx + 1].lower()
    except (ValueError, IndexError):
        return None
    if key in _HWACCEL_ARG_MAP:
        for var, val in _HWACCEL_ARG_MAP[key].items():
            os.environ[var] = val
        print(f"[hwaccel] Ustawiono akceleracj\u0119: {key}")
        for var, val in _HWACCEL_ARG_MAP[key].items():
            print(f"  {var} = {val}")
        return key
    return None

# Musi byc wywolane jeszcze przed importem PySide6:
_REQUESTED_HWACCEL = _apply_hwaccel_from_argv()

from i18n import I18n

def _check_deps():
    """Show error dialog if ffmpeg or ffprobe are missing."""
    from video_encoder import resolve_legacy_ffmpeg, resolve_legacy_ffprobe
    missing = []
    try:
        subprocess.run([resolve_legacy_ffmpeg("CPU"), "-version"], capture_output=True, timeout=5, check=True)
    except Exception:
        missing.append("ffmpeg")
    try:
        subprocess.run([resolve_legacy_ffprobe("CPU"), "-version"], capture_output=True, timeout=5, check=True)
    except Exception:
        missing.append("ffprobe")
        
    if missing:
        from PySide6.QtWidgets import QMessageBox, QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("Comparator")
        missing_str = "\n".join(f"  • {e}" for e in missing)
        QMessageBox.critical(
            None, I18n.tr("err_title"),
            I18n.tr("err_missing_deps", missing=missing_str)
        )
        sys.exit(1)

def _detect_gpu():
    """Wykryj dostepne GPU i ustaw zmienne srodowiskowe dla Qt FFmpeg.
    Jesli akceleracja zostala juz wybrana przez argument --hwaccel,
    ta funkcja tylko wykrywa liste dostepnych GPU i zwraca odpowiedni opis.

    Zwraca: (gpu_label: str, has_nvenc: bool, has_qsv: bool, has_amf: bool)
    """
    from video_encoder import resolve_legacy_ffmpeg
    try:
        p = subprocess.run(
            [resolve_legacy_ffmpeg("CPU"), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        out = p.stdout + p.stderr
    except Exception:
        out = ""
    has_nvenc = "h264_nvenc" in out or "hevc_nvenc" in out
    has_qsv   = "h264_qsv" in out or "hevc_qsv" in out
    has_amf   = "h264_amf" in out or "hevc_amf" in out

    if has_nvenc:
        try:
            subprocess.run(["nvidia-smi"], capture_output=True, timeout=2)
        except Exception:
            has_nvenc = False

    if sys.platform == 'win32':
        try:
            adapters = subprocess.run(['powershell', '-NoProfile', '-Command',
                'Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name'],
                capture_output=True, text=True, timeout=5).stdout.lower()
            if adapters:
                has_nvenc = has_nvenc and 'nvidia' in adapters
                has_qsv = has_qsv and 'intel' in adapters
                has_amf = has_amf and ('amd' in adapters or 'radeon' in adapters)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Jesli uzytkownik wybral akceleracje przez --hwaccel, szanujemy jego wybor;
    # ustalamy tylko etykiete do wyswietlenia w combo-boxie.
    if _REQUESTED_HWACCEL == "cpu":
        return "CPU", has_nvenc, has_qsv, has_amf
    elif _REQUESTED_HWACCEL == "nvidia":
        return "NVIDIA", has_nvenc, has_qsv, has_amf
    elif _REQUESTED_HWACCEL == "intel":
        return "Intel QSV", has_nvenc, has_qsv, has_amf
    elif _REQUESTED_HWACCEL == "amd":
        return "AMD AMF", has_nvenc, has_qsv, has_amf

    # Brak --hwaccel: auto-detekcja i ustawienie zmiennych srodowiskowych
    if has_nvenc:
        hw = "d3d11va"
        gpu = "NVIDIA"
    elif has_qsv:
        hw = "qsv"
        gpu = "Intel QSV"
    elif has_amf:
        hw = "d3d11va"
        gpu = "AMD AMF"
    else:
        hw = ""
        gpu = "CPU"

    if "QT_FFMPEG_HWACCEL" not in os.environ:
        os.environ["QT_FFMPEG_HWACCEL"] = hw
    if "QT_FFMPEG_DECODING_HW_DEVICE_TYPES" not in os.environ:
        if hw == "cuda":
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = "d3d11va,dxva2"
        elif hw == "qsv":
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = "qsv,d3d11va,dxva2"
        elif hw == "d3d11va":
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = "d3d11va,dxva2"
        else:
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = ""
    return gpu, has_nvenc, has_qsv, has_amf


_DEFAULT_GPU, _HAS_NVENC, _HAS_QSV, _HAS_AMF = _detect_gpu()

from PySide6.QtCore import Qt, QUrl, QTimer, QProcess, QSettings
from PySide6.QtGui import QShortcut, QKeySequence, QIcon, QPixmap, QPainter



from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog,
    QComboBox, QSlider, QMessageBox, QDoubleSpinBox, QLabel,
    QProgressBar, QVBoxLayout, QHBoxLayout, QSplitter, QSizePolicy,
    QCheckBox, QStackedWidget, QAbstractSpinBox, QLineEdit, QToolButton,
)

from export_live_preview import ExportLivePreview, choose_preview_size
from player_widget import PlayerWidget
from telemetry_factory import create_telemetry, NullTelemetry


def _make_audio_pixmap(overlay: str) -> QPixmap:
    p = QPixmap(28, 22)
    p.fill(Qt.GlobalColor.transparent)
    painter = QPainter(p)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = painter.pen()
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawRect(2, 7, 6, 8)
    painter.drawLine(8, 7, 15, 2)
    painter.drawLine(8, 15, 15, 20)
    if overlay == "mute":
        painter.drawLine(18, 4, 26, 18)
        painter.drawLine(18, 18, 26, 4)
    elif overlay == "left":
        painter.drawText(17, 18, "\u25C0")
    elif overlay == "right":
        painter.drawText(17, 18, "\u25B6")
    elif overlay == "both":
        painter.drawText(15, 18, "\u25C0\u25B6")
    painter.end()
    return p


_AUDIO_MODES = [
    ("mute",  "Wycisz"),
    ("left",  "Tylko lewy"),
    ("right", "Tylko prawy"),
    ("both",  "Oba"),
]



import ctypes
from ctypes import wintypes
from options_dialog import OptionsDialog, FULL_HD, UHD_4K, comparison_output_size

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

HTCLIENT = 1
HTCAPTION = 2
HTMINBUTTON = 8
HTMAXBUTTON = 9
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCLOSE = 20

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT)
    ]

class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(38)
        self.setStyleSheet("""
            QWidget#CustomTitleBar {
                background-color: #f3f3f3;
                border-bottom: 1px solid #dcdcdc;
            }
            QLabel {
                color: #1a1a1a;
            }
            QPushButton {
                background-color: #ffffff;
                color: #1a1a1a;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border-color: #adadad;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                color: #888888;
                border-color: #e0e0e0;
            }
            QComboBox, QDoubleSpinBox {
                background-color: #ffffff;
                color: #1a1a1a;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 12px;
            }
            QComboBox:hover, QDoubleSpinBox:hover {
                border-color: #adadad;
            }
            QComboBox:disabled, QDoubleSpinBox:disabled {
                background-color: #f5f5f5;
                color: #888888;
                border-color: #e0e0e0;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #1a1a1a;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                border: 1px solid #cccccc;
            }
            QPushButton#btn_export {
                background-color: #0078d4;
                color: #ffffff;
                border: 1px solid #005a9e;
                font-weight: bold;
            }
            QPushButton#btn_export:hover {
                background-color: #106ebe;
            }
            QPushButton#btn_export:pressed {
                background-color: #005a9e;
            }
            QPushButton#btn_export:disabled {
                background-color: #cccccc;
                color: #666666;
                border-color: #bbbbbb;
            }
            QPushButton.caption_btn {
                background-color: transparent;
                border: none;
                border-radius: 0px;
                font-size: 11px;
                color: #1a1a1a;
            }
            QPushButton.caption_btn:hover {
                background-color: #e5e5e5;
                color: #000000;
            }
            QPushButton.caption_btn:pressed {
                background-color: #cccccc;
            }
            QPushButton#caption_close:hover {
                background-color: #e81123;
                color: #ffffff;
            }
            QPushButton#caption_close:pressed {
                background-color: #c42b1c;
                color: #ffffff;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 0, 2)
        layout.setSpacing(6)

        # Title / branding
        self.title_label = QLabel("Comparator")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #1a1a1a; margin-right: 6px;")
        layout.addWidget(self.title_label)

        # Controls layout
        self.controls_layout = QHBoxLayout()
        self.controls_layout.setSpacing(6)
        layout.addLayout(self.controls_layout)

        layout.addStretch()

        # Window control buttons
        self.btn_min = QPushButton("―")
        self.btn_min.setProperty("class", "caption_btn")
        self.btn_min.setFixedSize(36, 34)

        self.btn_max = QPushButton("▢")
        self.btn_max.setProperty("class", "caption_btn")
        self.btn_max.setFixedSize(36, 34)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("caption_close")
        self.btn_close.setProperty("class", "caption_btn")
        self.btn_close.setFixedSize(36, 34)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(I18n.tr("app_title"))

        self.player1 = PlayerWidget(overlay_index=1)
        self.player2 = PlayerWidget(overlay_index=2)

        self.telemetry1 = None
        self.telemetry2 = None
        self._telemetry_jobs = {}
        self._telemetry_results = queue.Queue()
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.timeout.connect(self._poll_telemetry)
        self._telemetry_timer.start(100)
        self.running_tasks = {}
        self._syncing = False
        self._sync_offset_ms = 0  # ms: player2 position = player1 position - offset

        # ── title bar and options ─────────────────────────────────────
        self.title_bar = CustomTitleBar(self)
        self.options_data = OptionsDialog.load_settings()
        self.player1.set_overlay_style(
            self.options_data.get("overlay_font_scale", 1.0),
            self.options_data.get("overlay_opacity", 1.0)
        )
        self.player2.set_overlay_style(
            self.options_data.get("overlay_font_scale", 1.0),
            self.options_data.get("overlay_opacity", 1.0)
        )

        # Primary load button (two files at once)
        self._last_dir = ""
        self.btn_load = QPushButton(I18n.tr("btn_load"))
        self.btn_load.setToolTip(I18n.tr("btn_load_tooltip"))
        self.btn_load.clicked.connect(self.load_two_videos)
        self.load_button = self.btn_load

        # Options button
        self.btn_options = QPushButton(I18n.tr("btn_options"))
        self.btn_options.setToolTip(I18n.tr("btn_options_tooltip"))
        self.btn_options.clicked.connect(self._open_options)

        # Legacy buttons for test backward compatibility
        self.btn_video1 = QPushButton(I18n.tr("btn_video1"))
        self.btn_video2 = QPushButton(I18n.tr("btn_video2"))
        self.btn_export = QPushButton(I18n.tr("btn_export"))
        self.btn_export.setObjectName("btn_export")

        self.layout_mode = QComboBox()
        self.layout_mode.addItems([I18n.tr("layout_lr"), I18n.tr("layout_ud")])
        self.layout_mode.currentIndexChanged.connect(self._build_seekbar_layout)

        # -- audio mode selector --
        self.audio_combo = QComboBox()
        _AUDIO_MODES_KEYS = ["mute", "left", "right", "both"]
        for key in _AUDIO_MODES_KEYS:
            label = I18n.tr(f"audio_{key}")
            self.audio_combo.addItem(QIcon(_make_audio_pixmap(key)), label)
        self.audio_combo.currentIndexChanged.connect(lambda idx: self._set_audio_mode(idx))
        self.audio_combo.setToolTip(I18n.tr("audio_tooltip"))
        self.audio_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        # -- HEVC profile controls --
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            I18n.tr("preset_fast"),
            I18n.tr("preset_balanced"),
            I18n.tr("preset_quality")
        ])
        self.preset_combo.setCurrentIndex(1)  # Default: Zbalansowany
        self.preset_combo.setToolTip(I18n.tr("preset_tooltip"))
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.encoder_combo = QComboBox()
        # Zbuduj liste na podstawie wykrytego sprzetu (niezaleznie od _REQUESTED_HWACCEL)
        avail = ["CPU"]
        if _HAS_NVENC:
            avail.append("NVIDIA")
        if _HAS_QSV:
            avail.append("Intel QSV")
        if _HAS_AMF:
            avail.append("AMD AMF")
        if len(avail) == 1 and _REQUESTED_HWACCEL is None:  # detekcja nie znalazla GPU → pokaz wszystkie
            avail = ["CPU", "NVIDIA", "Intel QSV", "AMD AMF"]
        self.encoder_combo.addItems(avail)
        # Zaznacz aktualnie uzywana opcje
        for i, e in enumerate(avail):
            if _DEFAULT_GPU in e:
                self.encoder_combo.setCurrentIndex(i)
                break
        self.encoder_combo.setToolTip(I18n.tr("encoder_tooltip"))
        self.encoder_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        # -- decoder controls (for playback/preview) --
        self.decoder_label = QLabel(I18n.tr("decoder_label"))
        self.decoder_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.decoder_combo = QComboBox()
        self.decoder_combo.addItems(avail)
        # Zaznacz aktualnie uzywana opcje
        for i, e in enumerate(avail):
            if _DEFAULT_GPU in e:
                self.decoder_combo.setCurrentIndex(i)
                break
        self.decoder_combo.setToolTip(I18n.tr("decoder_tooltip"))
        self.decoder_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.bitrate_spin = QDoubleSpinBox()
        self.bitrate_spin.setRange(0.5, 200.0)
        self.bitrate_spin.setValue(10.0)
        self.bitrate_spin.setSuffix(" Mbps")
        self.bitrate_spin.setSingleStep(1.0)
        self.bitrate_spin.setDecimals(1)
        self.bitrate_spin.setToolTip(I18n.tr("bitrate_tooltip"))
        self.bitrate_spin.setFixedWidth(120)

        bitrate_label = QLabel(":")
        bitrate_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.scale_combo = QComboBox()
        self.scale_combo.addItem("×1", 1)
        self.scale_combo.addItem("×2", 2)
        self.scale_combo.addItem("×4", 4)
        initial_speed = OptionsDialog.load_settings().get("playback_speed", 1)
        self.scale_combo.setCurrentIndex(max(0, self.scale_combo.findData(initial_speed)))
        self.scale_combo.setToolTip(I18n.tr("playback_speed_tooltip"))
        self.scale_combo.setFixedWidth(78)

        # ── per-player seekbars and frame-step buttons ─────────────
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(36, 28)
        self.btn_play.setIcon(
            self.style().standardIcon(
                QApplication.style().StandardPixmap.SP_MediaPlay
            )
        )
        self.btn_play.clicked.connect(self.toggle_pause)

        self._frame_step_ms = 33  # ~1 klatka przy 30 fps

        # -- shared seekbar (controls both players) --
        self.shared_seekbar = QSlider(Qt.Orientation.Horizontal)
        self.shared_seekbar.setRange(0, 1000)
        self.shared_seekbar.setValue(0)
        self.shared_seekbar.sliderPressed.connect(self._on_shared_seek_pressed)
        self.shared_seekbar.sliderMoved.connect(self._on_shared_seek_moved)
        self.shared_seekbar.sliderReleased.connect(self._on_shared_seek_released)
        self._was_playing_before_shared_seek = False

        self.label_shared_time = QLabel("0:00 / 0:00")
        self.label_shared_time.setFixedWidth(110)

        def _make_seekbar() -> QSlider:
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 1000)
            s.setValue(0)
            return s

        self.seekbar1 = _make_seekbar()
        self.seekbar2 = _make_seekbar()

        self.seekbar1.sliderPressed.connect(lambda: self._on_seek_pressed(1))
        self.seekbar1.sliderMoved.connect(lambda v: self._on_seek_moved(1, v))
        self.seekbar1.sliderReleased.connect(lambda: self._on_seek_released(1))
        self.seekbar2.sliderPressed.connect(lambda: self._on_seek_pressed(2))
        self.seekbar2.sliderMoved.connect(lambda v: self._on_seek_moved(2, v))
        self.seekbar2.sliderReleased.connect(lambda: self._on_seek_released(2))

        self._was_playing_before_seek = [False, False]  # per-player

        self.btn_rev1 = QPushButton("\u25C0")
        self.btn_fwd1 = QPushButton("\u25B6")
        self.btn_rev2 = QPushButton("\u25C0")
        self.btn_fwd2 = QPushButton("\u25B6")
        for btn in (self.btn_rev1, self.btn_fwd1, self.btn_rev2, self.btn_fwd2):
            btn.setFixedSize(28, 28)
        self.btn_rev1.clicked.connect(lambda: self._step_frame(1, -1))
        self.btn_fwd1.clicked.connect(lambda: self._step_frame(1, 1))
        self.btn_rev2.clicked.connect(lambda: self._step_frame(2, -1))
        self.btn_fwd2.clicked.connect(lambda: self._step_frame(2, 1))

        self.label_time1 = QLabel("0:00 / 0:00")
        self.label_time2 = QLabel("0:00 / 0:00")
        self.label_time1.setFixedWidth(130)
        self.label_time2.setFixedWidth(130)

        # -- auto-sync button --
        self.btn_autosync = QPushButton(I18n.tr("btn_autosync"))
        self.btn_autosync.setToolTip(I18n.tr("btn_autosync_tooltip"))
        self.btn_autosync.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_autosync.clicked.connect(self._auto_sync)

        # -- overlay toggle checkbox --
        self.chk_overlay = QCheckBox(I18n.tr("chk_overlay"))
        self.chk_overlay.setChecked(True)
        self.chk_overlay.stateChanged.connect(self._on_overlay_toggled)

        self.export_preview = ExportLivePreview(self)
        self.export_preview.cancel.clicked.connect(self._cancel_export)

        # ── progress bar ──────────────────────────────────────────────
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_progress.setFixedHeight(18)
        self.export_progress.setTextVisible(True)
        self.export_progress.setVisible(False)

        # ── layout ────────────────────────────────────────────────────
        self.main_widget = QWidget()
        self.splitter = QSplitter()

        self.layout_mode.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems([
            I18n.tr("backend_auto"),
            I18n.tr("backend_d3d11"),
            I18n.tr("backend_legacy"),
        ])
        self.backend_combo.setToolTip(I18n.tr("backend_tooltip"))
        self.backend_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        # Populate top bar controls
        self.title_bar.controls_layout.addWidget(self.btn_load)
        self.title_bar.controls_layout.addWidget(self.layout_mode)
        self.title_bar.controls_layout.addWidget(self.audio_combo)
        self.title_bar.controls_layout.addWidget(self.decoder_label)
        self.title_bar.controls_layout.addWidget(self.decoder_combo)
        self.title_bar.controls_layout.addWidget(self.btn_export)
        self.title_bar.controls_layout.addWidget(self.preset_combo)
        self.title_bar.controls_layout.addWidget(self.encoder_combo)
        self.title_bar.controls_layout.addWidget(bitrate_label)
        self.title_bar.controls_layout.addWidget(self.bitrate_spin)
        self.title_bar.controls_layout.addWidget(QLabel(I18n.tr("playback_speed_label")))
        self.title_bar.controls_layout.addWidget(self.scale_combo)
        self.title_bar.controls_layout.addWidget(self.btn_options)

        self.title_bar.btn_min.clicked.connect(self.showMinimized)
        self.title_bar.btn_max.clicked.connect(self._toggle_maximize)
        self.title_bar.btn_close.clicked.connect(self.close)

        # Convenient references on title_bar
        self.title_bar.btn_load = self.btn_load
        self.title_bar.load_button = self.btn_load
        self.title_bar.btn_options = self.btn_options
        self.title_bar.btn_export = self.btn_export

        # --- seekbar row for player 1 (arrows on right) ---
        self.seek_row1 = QWidget()
        self.seek_row1.setFixedHeight(40)
        sr1 = QHBoxLayout(self.seek_row1)
        sr1.setContentsMargins(4, 4, 4, 4)
        sr1.setSpacing(4)
        self.seekbar1.setFixedHeight(20)
        sr1.addWidget(self.label_time1)
        sr1.addWidget(self.seekbar1, 1)
        sr1.addWidget(self.btn_rev1)
        sr1.addWidget(self.btn_fwd1)

        # --- seekbar row for player 2 (arrows on left) ---
        self.seek_row2 = QWidget()
        self.seek_row2.setFixedHeight(40)
        sr2 = QHBoxLayout(self.seek_row2)
        sr2.setContentsMargins(4, 4, 4, 4)
        sr2.setSpacing(4)
        self.seekbar2.setFixedHeight(20)
        sr2.addWidget(self.btn_rev2)
        sr2.addWidget(self.btn_fwd2)
        sr2.addWidget(self.seekbar2, 1)
        sr2.addWidget(self.label_time2)

        # --- seekbar area (both side by side) ---
        self.seekbar_area = QWidget()
        sa = QHBoxLayout(self.seekbar_area)
        sa.setContentsMargins(4, 2, 4, 2)
        sa.setSpacing(4)
        sa.addWidget(self.seek_row1)
        sa.addWidget(self.seek_row2)
        sa.addWidget(self.btn_autosync)

        root = QVBoxLayout(self.main_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.title_bar)
        root.addWidget(self.export_progress)

        # --- shared seekbar row ---
        shared_row = QHBoxLayout()
        shared_row.setContentsMargins(4, 4, 4, 4)
        shared_row.addWidget(self.btn_play)
        shared_row.addWidget(self.label_shared_time)
        shared_row.addWidget(self.shared_seekbar, 1)
        shared_row.addWidget(self.chk_overlay)

        root.addLayout(shared_row)

        # --- main viewing area: normal dual players (page 0) vs export preview canvas (page 1) ---
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.splitter)
        self.preview_stack.addWidget(self.export_preview)
        root.addWidget(self.preview_stack, 1)
        root.addWidget(self.seekbar_area)

        self.splitter.addWidget(self.player1)
        self.splitter.addWidget(self.player2)
        self._build_seekbar_layout(self.layout_mode.currentIndex())
        self.setCentralWidget(self.main_widget)

        # ── signals ───────────────────────────────────────────────────
        self.btn_video1.clicked.connect(self.load_video1)
        self.btn_video2.clicked.connect(self.load_video2)
        self.btn_export.clicked.connect(self.export_video)
        self.decoder_combo.currentTextChanged.connect(self._on_decoder_changed)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.encoder_combo.currentTextChanged.connect(self._on_encoder_changed_interlock)
        self.layout_mode.currentIndexChanged.connect(self._refresh_nvidia_export_modes)
        self.preset_combo.currentIndexChanged.connect(self._refresh_nvidia_export_modes)
        self._nvidia_probe_queue = queue.Queue()
        self._nvidia_probe_generation = 0
        self._nvidia_dual4k_supported = False
        self._nvidia_dual4k_reason = I18n.tr("resolution_unavailable_default")
        self._dual4k_support_by_padding = {False: False, True: False}
        self._dual4k_reason_by_padding = {False: self._nvidia_dual4k_reason, True: self._nvidia_dual4k_reason}
        self._restore_4k_pending = self.options_data.get("comparison_resolution", FULL_HD) == UHD_4K
        self.scale_combo.currentIndexChanged.connect(self._on_scale_mode_changed)

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.space_shortcut.activated.connect(self.toggle_pause)

        # Export state
        from preview_sync import PreviewSync
        self._preview_sync = PreviewSync((self.player1, self.player2))
        self._manual_offset = False
        self._export_results = queue.Queue()
        self._preview_failure_validation_results = queue.Queue()
        self._preview_failure_validation_pending = False
        self._export_expected_size = None
        self._export_log = ''
        self._export_pending = ''
        self._process_error = ''
        self._export_started_at = None
        self._export_process = None
        self._export_duration = 0.0
        self._export_stack = ""
        self._export_ass1 = None
        self._export_ass2 = None
        self._export_tmpdir = None
        self._export_out_path = ""
        self._is_exporting = False
        self.export_preview.stop()
        self._cancel_requested = False
        self._active_backend = ""
        self._last_gpu_metrics = None
        self._last_gpu_error = ""
        self._ffmpeg_log_path = None

        # Audio starts muted – jawnie wołamy, bo setCurrentIndex(0) nie emituje sygnału
        self._set_audio_mode(0)
        self.audio_combo.setCurrentIndex(0)

    # ══════════════════════════════════════════════════════════════════
    # Audio
    # ══════════════════════════════════════════════════════════════════
    def _set_audio_mode(self, idx: int):
        mode = _AUDIO_MODES[idx][0]
        print(f"[audio] Tryb: {mode}")
        if mode == "mute":
            self.player1.audio.setVolume(0.0)
            self.player2.audio.setVolume(0.0)
        elif mode == "left":
            self.player1.audio.setVolume(1.0)
            self.player2.audio.setVolume(0.0)
        elif mode == "right":
            self.player1.audio.setVolume(0.0)
            self.player2.audio.setVolume(1.0)
        elif mode == "both":
            self.player1.audio.setVolume(0.5)
            self.player2.audio.setVolume(0.5)

    def _on_backend_changed(self, idx: int):
        # 1 = D3D11 Zero-Copy; D3D11 requires GPU encoder
        if idx == 1 and self.encoder_combo.currentText() == "CPU":
            for i in range(self.encoder_combo.count()):
                if self.encoder_combo.itemText(i) != "CPU":
                    self.encoder_combo.setCurrentIndex(i)
                    break
        self._refresh_nvidia_export_modes()

    def _on_encoder_changed_interlock(self, text: str):
        # If CPU selected, switch away from D3D11 Zero-Copy to Legacy FFmpeg
        if text == "CPU" and self.backend_combo.currentIndex() == 1:
            self.backend_combo.setCurrentIndex(2)
        self._refresh_nvidia_export_modes()

    def _on_scale_mode_changed(self, *_args):
        """Persist playback speed separately from comparison resolution."""
        speed = self.scale_combo.currentData()
        if speed in (1, 2, 4):
            self.options_data["playback_speed"] = speed
            settings = QSettings("Comparator", "Comparator")
            settings.setValue("playback_speed", speed)
            settings.sync()

    def _dual4k_item_index(self):
        return -1

    def _remove_dual4k_option(self, explain=False, reason=None):
        self._nvidia_dual4k_supported = False
        self._nvidia_dual4k_reason = reason or self._nvidia_dual4k_reason
        pending_unavailable = (
            explain and self._restore_4k_pending
            and self.options_data.get("comparison_resolution") == UHD_4K
        )
        if pending_unavailable:
            self.options_data["comparison_resolution"] = FULL_HD
            OptionsDialog.save_resolution(FULL_HD)
            self._restore_4k_pending = False
            if explain:
                message = I18n.tr("resolution_fallback_message").format(reason=self._nvidia_dual4k_reason)
                print(f"[export] {message}")
                QMessageBox.information(self, I18n.tr("resolution_fallback_title"), message)

    def _refresh_nvidia_export_modes(self, *_args):
        """Probe exact dual-4K encoder dimensions outside the GUI thread."""
        self._nvidia_probe_generation += 1
        generation = self._nvidia_probe_generation
        has_inputs = all(
            provider is not None and getattr(provider, "filename", "")
            for provider in (self.telemetry1, self.telemetry2)
        )
        if not has_inputs:
            self._remove_dual4k_option(reason="Wczytaj dwa filmy 3840 × 2160.")
            return

        from video_encoder import resolve_legacy_ffmpeg, resolve_legacy_ffprobe, probe_encoder_size
        import nvidia_modern

        input_paths = (str(self.telemetry1.filename), str(self.telemetry2.filename))
        layout = "left_right" if self.layout_mode.currentIndex() == 0 else "top_bottom"
        preset = ("speed", "balanced", "quality")[self.preset_combo.currentIndex()]
        hw = self.encoder_combo.currentText()
        backend_mode = self.backend_combo.currentIndex()
        ffmpeg_exe = resolve_legacy_ffmpeg(hw)
        ffprobe_exe = resolve_legacy_ffprobe(hw)
        self.scale_combo.setToolTip("Sprawdzam dokładne wymiary Podwójnego 4K…")

        def probe():
            modern_ok, modern_detail = False, "NVIDIA Modern niewybrane"
            if hw == "NVIDIA" and backend_mode == 0:
                modern_ok, modern_detail = nvidia_modern.probe_nvidia_modern(ffmpeg_exe, input_paths[0], preset)
            encoder_name = {"NVIDIA": "hevc_nvenc", "AMD AMF": "hevc_amf", "Intel QSV": "hevc_qsv", "CPU": "libx265"}.get(hw, "libx265")
            capabilities = {}
            for pad in (False, True):
                target = (7680, 4320) if pad else ((7680, 2160) if layout == "left_right" else (3840, 4320))
                if hw == "NVIDIA" and modern_ok and backend_mode == 0:
                    dual_ok, dual_detail = nvidia_modern.probe_nvidia_dual4k(ffmpeg_exe, layout, preset, pad)
                else:
                    dual_ok, dual_detail = probe_encoder_size(encoder_name, *target, ffmpeg_exe)
                if not dual_ok:
                    # Keep the full FFmpeg/encoder diagnostic in the log. The
                    # Options dialog is persistent UI, so don't put the whole
                    # multiline FFmpeg trace in its status label.
                    print(
                        f"[export] {hw}_DUAL4K_PROBE_RAW_DETAIL="
                        f"{target[0]}x{target[1]}: {dual_detail}"
                    )
                    dual_detail = I18n.tr("resolution_encoder_probe_failed").format(
                        encoder=hw, width=target[0], height=target[1]
                    )
                capabilities[pad] = (dual_ok, dual_detail)
            material_detail = ""
            try:
                sizes = []
                for path in input_paths:
                    result = subprocess.run(
                        [ffprobe_exe, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
                        capture_output=True, text=True, timeout=20,
                    )
                    if result.returncode:
                        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
                    dimensions = re.findall(r"\d+", result.stdout)
                    if len(dimensions) < 2:
                        raise RuntimeError(f"Nieczytelne wymiary FFprobe: {result.stdout!r}")
                    sizes.append((int(dimensions[0]), int(dimensions[1])))
                if sizes[0] != (3840, 2160) or sizes[1] != (3840, 2160):
                    material_detail = "Tryb 4K UHD wymaga dwóch wejść 3840 × 2160."
                    capabilities = {pad: (False, material_detail) for pad in (False, True)}
                elif sizes[0] != sizes[1]:
                    material_detail = "Wymiary obu materiałów muszą być zgodne."
                    capabilities = {pad: (False, material_detail) for pad in (False, True)}
            except Exception as exc:
                material_detail = f"Nie można sprawdzić wymiarów materiałów: {exc}"
                capabilities = {pad: (False, material_detail) for pad in (False, True)}
            self._nvidia_probe_queue.put((generation, modern_ok, modern_detail, capabilities, material_detail))

        threading.Thread(target=probe, daemon=True).start()

    def _poll_nvidia_export_modes(self):
        latest = None
        while not self._nvidia_probe_queue.empty():
            latest = self._nvidia_probe_queue.get_nowait()
        if latest is None:
            return
        generation, modern_ok, modern_detail, capabilities, material_detail = latest
        if generation != self._nvidia_probe_generation:
            return
        hw = self.encoder_combo.currentText()
        print(f"[export] {hw}_MODERN_PROBE={'PASS' if modern_ok else 'FAIL'}")
        if not modern_ok and hw == "NVIDIA":
            print(f"[export] NVIDIA_MODERN_PROBE_DETAIL={modern_detail}")
        for pad, (dual_ok, dual_detail) in capabilities.items():
            label = "PADDED_8K" if pad else "UNPADDED_DUAL4K"
            print(f"[export] {hw}_{label}_PROBE={'PASS' if dual_ok else 'FAIL'}")
            if not dual_ok:
                print(f"[export] {hw}_{label}_PROBE_DETAIL={material_detail or dual_detail}")
        self._dual4k_support_by_padding = {pad: bool(value[0]) for pad, value in capabilities.items()}
        self._dual4k_reason_by_padding = {pad: (material_detail or value[1]) for pad, value in capabilities.items()}
        selected_pad = bool(self.options_data.get("pad_to_16_9", True))
        dual_ok, dual_detail = capabilities.get(selected_pad, (False, "Brak wyniku probe."))
        if dual_ok:
            self._nvidia_dual4k_supported = True
            self._nvidia_dual4k_reason = ""
            self.scale_combo.setToolTip(I18n.tr("playback_speed_tooltip"))
            self._restore_4k_pending = False
        else:
            reason = material_detail or dual_detail
            if not reason:
                reason = f"Wybrany koder {hw} nie obsługuje docelowego wymiaru Podwójnego 4K."
            self._nvidia_dual4k_reason = reason
            if self.options_data.get("comparison_resolution") == UHD_4K:
                self._restore_4k_pending = False
                self.options_data["comparison_resolution"] = FULL_HD
                OptionsDialog.save_resolution(FULL_HD)
                message = I18n.tr("resolution_fallback_message").format(reason=reason)
                print(f"[export] {message}")
                QMessageBox.information(self, I18n.tr("resolution_fallback_title"), message)

    def _on_decoder_changed(self, text: str):
        """Ustaw akcelerację sprzętową i zrestartuj proces, by Qt Multimedia
        zaaplikowało nowe ustawienie przy inicjalizacji pluginu FFmpeg."""
        label_to_key = {
            "CPU":       "cpu",
            "NVIDIA":    "nvidia",
            "Intel QSV": "intel",
            "AMD AMF":   "amd",
        }
        key = label_to_key.get(text)
        if key is None:
            return

        # Zbuduj czystą listę argv bez --hwaccel <x>
        clean_argv = []
        skip_next = False
        for a in sys.argv:
            if skip_next:
                skip_next = False
                continue
            if a == "--hwaccel":
                skip_next = True
                continue
            clean_argv.append(a)

        new_argv = clean_argv + ["--hwaccel", key]
        print(f"[hwaccel] Restart z argumentem --hwaccel {key}")
        print(f"  Komenda: {sys.executable} {' '.join(new_argv)}")

        # Uruchom nowy proces i natychmiast zakoncz biezacy
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable] + new_argv[1:])
        else:
            subprocess.Popen([sys.executable] + new_argv)
        sys.exit(0)

    # ══════════════════════════════════════════════════════════════════
    # Layout
    # ══════════════════════════════════════════════════════════════════
    def _build_seekbar_layout(self, mode_index: int):
        """Rebuild splitter contents based on layout mode."""
        if mode_index == 0:
            # Lewo / Prawo
            self.splitter.setOrientation(Qt.Horizontal)
        else:
            # Góra / Dół
            self.splitter.setOrientation(Qt.Vertical)

    # ══════════════════════════════════════════════════════════════════
    # Seekbar / tick
    # ══════════════════════════════════════════════════════════════════
    def _tick(self):
        self._preview_sync.tick()
        self._poll_export_preparation()
        self._poll_preview_failure_validation()
        self._poll_nvidia_export_modes()
        if self.chk_overlay.isChecked():
            if self.telemetry1 is not None:
                sec = self.player1.position() / 1000.0
                self.player1.set_overlay(self.telemetry1.get_overlay_text(sec))
            if self.telemetry2 is not None:
                sec = self.player2.position() / 1000.0
                self.player2.set_overlay(self.telemetry2.get_overlay_text(sec))
        else:
            self.player1.set_overlay("")
            self.player2.set_overlay("")

        self._update_seekbar(1)
        self._update_seekbar(2)
        self._update_shared_seekbar()

        if self._preview_sync.playing:
            self.btn_play.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_MediaPause))
        else:
            self.btn_play.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_MediaPlay))

    def _update_shared_seekbar(self):
        if self.shared_seekbar.isSliderDown():
            return
        dur = self._preview_sync.duration()
        pos = self._preview_sync.current()
        if dur > 0:
            self.shared_seekbar.setValue(int(pos * 1000 / dur))
        def fmt(t: int) -> str:
            s = t // 1000
            return f"{s // 60}:{s % 60:02d}"
        self.label_shared_time.setText(f"{fmt(pos)} / {fmt(dur)}")

    def _on_shared_seek_pressed(self):
        self._was_playing_before_shared_seek = self._preview_sync.playing
        self._preview_sync.pause()

    def _on_shared_seek_moved(self, value: int):
        dur = self._preview_sync.duration()
        if dur > 0:
            pos = int(value * dur / 1000)
            def fmt(t: int) -> str:
                s = t // 1000
                return f"{s // 60}:{s % 60:02d}"
            self.label_shared_time.setText(f"{fmt(pos)} / {fmt(dur)}")

    def _on_shared_seek_released(self):
        self._preview_sync.seek(int(self.shared_seekbar.value() * self._preview_sync.duration() / 1000))
        if self._was_playing_before_shared_seek:
            self._preview_sync.play()
            self._was_playing_before_shared_seek = False

    def _update_seekbar(self, player_idx: int):
        player = self.player1 if player_idx == 1 else self.player2
        seekbar = self.seekbar1 if player_idx == 1 else self.seekbar2
        label = self.label_time1 if player_idx == 1 else self.label_time2

        pos = player.position()
        dur = player.player.duration()
        if dur > 0 and not seekbar.isSliderDown():
            seekbar.setValue(int(pos * 1000 / dur))

        def fmt(t: int) -> str:
            s = t // 1000
            return f"{s // 60}:{s % 60:02d}"
        label.setText(f"{fmt(pos)} / {fmt(dur)}")

    def _on_seek_pressed(self, player_idx):
        self._was_playing_before_seek[player_idx - 1] = self._preview_sync.playing
        self._preview_sync.pause()

    def _on_seek_moved(self, player_idx: int, value: int):
        player = self.player1 if player_idx == 1 else self.player2
        dur = player.player.duration()
        label = self.label_time1 if player_idx == 1 else self.label_time2
        if dur > 0:
            pos = int(value * dur / 1000)
            def fmt(t: int) -> str:
                s = t // 1000
                return f"{s // 60}:{s % 60:02d}"
            label.setText(f"{fmt(pos)} / {fmt(dur)}")

    def _recalc_offset_from_positions(self, changed_index=None, changed_position=None):
        """Przelicz offset synchronizacji z aktualnych pozycji obu film\u00f3w."""
        if self.telemetry1 is not None and self.telemetry2 is not None:
            p1 = self.player1.position()
            p2 = self.player2.position()
            if changed_index == 1: p1 = changed_position
            if changed_index == 2: p2 = changed_position
            self._sync_offset_ms = p1 - p2
            self._manual_offset = True
            self._preview_sync.set_offset(self._sync_offset_ms, max(p1, p2), seek=False)
            print(I18n.tr("manual_sync_offset", ms=self._sync_offset_ms))

    def _on_seek_released(self, player_idx: int):
        player = self.player1 if player_idx == 1 else self.player2
        seekbar = self.seekbar1 if player_idx == 1 else self.seekbar2
        dur = player.player.duration()
        if dur > 0:
            pos = int(seekbar.value() * dur / 1000)
            self._syncing = True
            try:
                player.set_position(pos)
            finally:
                self._syncing = False
            self._recalc_offset_from_positions(player_idx, pos)
        if self._was_playing_before_seek[player_idx - 1]:
            self._preview_sync.play()
            self._was_playing_before_seek[player_idx - 1] = False

    def _step_frame(self, player_idx: int, direction: int):
        """Przesuń o 1 klatkę (direction: -1 = wstecz, +1 = naprzód)."""
        self._preview_sync.pause()
        player = self.player1 if player_idx == 1 else self.player2
        step = direction * self._frame_step_ms
        new_pos = max(0, player.position() + step)
        dur = player.player.duration()
        if new_pos <= dur:
            self._syncing = True
            try:
                player.set_position(new_pos)
            finally:
                self._syncing = False
            self._recalc_offset_from_positions(player_idx, new_pos)

    def toggle_pause(self):
        if self._preview_sync.playing:
            self._preview_sync.pause()
        else:
            self._preview_sync.play()

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if hasattr(self, 'title_bar') and self.title_bar is not None:
                if self.isMaximized():
                    self.centralWidget().layout().setContentsMargins(8, 8, 8, 8)
                    self.title_bar.btn_max.setText("🗗")
                else:
                    self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)
                    self.title_bar.btn_max.setText("▢")
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            try:
                from ctypes import c_int, byref, Structure, windll
                class MARGINS(Structure):
                    _fields_ = [
                        ("cxLeftWidth", c_int),
                        ("cxRightWidth", c_int),
                        ("cyTopHeight", c_int),
                        ("cyBottomHeight", c_int)
                    ]
                margins = MARGINS(1, 1, 1, 1)
                windll.dwmapi.DwmExtendFrameIntoClientArea(int(self.winId()), byref(margins))
            except Exception:
                pass

    def _is_interactive_titlebar_control(self, widget):
        """Return True if widget or any of its parents up to title_bar is an interactive control."""
        if widget is None or not hasattr(self, 'title_bar') or self.title_bar is None:
            return False
        tb = self.title_bar
        if widget is tb or widget is getattr(tb, 'title_label', None):
            return False
        cur = widget
        while cur is not None and cur is not tb:
            if isinstance(cur, (QPushButton, QComboBox, QAbstractSpinBox, QLineEdit, QCheckBox, QToolButton)):
                return True
            cur = cur.parentWidget()
        return False

    def nativeEvent(self, event_type, message):
        if sys.platform != "win32":
            return super().nativeEvent(event_type, message)
        try:
            msg = MSG.from_address(int(message))
            if msg.message == WM_NCCALCSIZE:
                return True, 0
            elif msg.message == WM_NCHITTEST:
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local_pt = self.mapFromGlobal(QPoint(x, y))

                # 1. Title bar interactive controls and snap layouts (highest priority)
                if hasattr(self, 'title_bar') and self.title_bar is not None:
                    tb_pt = self.title_bar.mapFromGlobal(QPoint(x, y))
                    if self.title_bar.rect().contains(tb_pt):
                        # Snap layouts on max button
                        max_pt = self.title_bar.btn_max.mapFromGlobal(QPoint(x, y))
                        if self.title_bar.btn_max.rect().contains(max_pt):
                            return True, HTMAXBUTTON

                        child = self.title_bar.childAt(tb_pt)
                        if self._is_interactive_titlebar_control(child):
                            return True, HTCLIENT

                # 2. Window borders for resizing (when not maximized)
                if not self.isMaximized():
                    border = 8
                    w = self.width()
                    h = self.height()
                    lx = local_pt.x()
                    ly = local_pt.y()

                    top = ly < border
                    bottom = ly > h - border
                    left = lx < border
                    right = lx > w - border

                    if top and left: return True, HTTOPLEFT
                    if top and right: return True, HTTOPRIGHT
                    if bottom and left: return True, HTBOTTOMLEFT
                    if bottom and right: return True, HTBOTTOMRIGHT
                    if top: return True, HTTOP
                    if bottom: return True, HTBOTTOM
                    if left: return True, HTLEFT
                    if right: return True, HTRIGHT

                # 3. Draggable empty title bar area or title label
                if hasattr(self, 'title_bar') and self.title_bar is not None:
                    tb_pt = self.title_bar.mapFromGlobal(QPoint(x, y))
                    if self.title_bar.rect().contains(tb_pt):
                        return True, HTCAPTION

                return True, HTCLIENT
        except Exception:
            pass
        return super().nativeEvent(event_type, message)

    def load_two_videos(self):
        """Dedicated UI handler for 'Wczytaj' button."""
        print("LOAD_BUTTON_CLICKED")
        return self.load_videos()

    def load_videos(self, files=None):
        """Transactional loader for exactly two video files."""
        # When called as a Qt slot from clicked(bool), files will be a boolean (False).
        if files is None or isinstance(files, bool):
            print("LOAD_DIALOG_OPENING")
            last_dir = getattr(self, "_last_dir", "") or ""
            files, _ = QFileDialog.getOpenFileNames(
                self,
                I18n.tr("load_videos_title"),
                last_dir,
                I18n.tr("video_filter")
            )
            count = len(files) if files else 0
            print(f"LOAD_DIALOG_RESULT_COUNT={count}")

        if not files:
            return False

        if len(files) != 2:
            QMessageBox.critical(
                self,
                I18n.tr("err_title"),
                I18n.tr("load_two_files_required")
            )
            return False

        path1, path2 = str(files[0]), str(files[1])
        print(f"LOAD_VIDEO1={path1}")
        print(f"LOAD_VIDEO2={path2}")
        print(f"Video 1: {path1}")
        print(f"Video 2: {path2}")

        # Update last directory from selected file
        p1 = Path(path1)
        if p1.parent.exists():
            self._last_dir = str(p1.parent)

        self._start_telemetry(1, path1)
        self.player1.setSource(QUrl.fromLocalFile(path1))
        self.player1.set_overlay("")

        self._start_telemetry(2, path2)
        self.player2.setSource(QUrl.fromLocalFile(path2))
        self.player2.set_overlay("")
        self._refresh_nvidia_export_modes()

        self._manual_offset = False
        self._recalc_sync_offset()
        self._connect_sync()
        self._preview_sync.play()
        return True

    def _open_options(self):
        active_resolution = self.options_data.get("comparison_resolution", FULL_HD)
        layout = "left_right" if self.layout_mode.currentIndex() == 0 else "top_bottom"
        dlg = OptionsDialog(
            self, on_preview_change=self._on_options_preview_change,
            active_resolution=active_resolution,
            resolution_available=self._nvidia_dual4k_supported,
            resolution_reason=self._nvidia_dual4k_reason,
            layout=layout,
            resolution_availability_by_padding=self._dual4k_support_by_padding,
            resolution_reason_by_padding=self._dual4k_reason_by_padding,
        )
        dlg.settingsApplied.connect(self._on_options_applied)
        dlg.comparisonResolutionApplied.connect(self._on_comparison_resolution_applied)
        dlg.exec()
        self.options_data.update(OptionsDialog.load_settings())

    def _on_options_preview_change(self, font_scale: float, opacity: float):
        self.player1.set_overlay_style(font_scale, opacity)
        self.player2.set_overlay_style(font_scale, opacity)

    def _on_options_applied(self, font_scale: float, opacity: float, pad_to_4k: bool):
        self.options_data["overlay_font_scale"] = font_scale
        self.options_data["overlay_opacity"] = opacity
        self.options_data["pad_to_4k"] = bool(pad_to_4k)
        self.options_data["pad_to_16_9"] = bool(pad_to_4k)
        if hasattr(self, "_dual4k_support_by_padding"):
            self._nvidia_dual4k_supported = bool(self._dual4k_support_by_padding.get(bool(pad_to_4k), False))
            if not self._nvidia_dual4k_supported:
                self._nvidia_dual4k_reason = self._dual4k_reason_by_padding.get(bool(pad_to_4k), "")
        self.player1.set_overlay_style(font_scale, opacity)
        self.player2.set_overlay_style(font_scale, opacity)

    def _on_comparison_resolution_applied(self, resolution: str):
        pad = bool(self.options_data.get("pad_to_16_9", True))
        dual4k_supported = bool(self._dual4k_support_by_padding.get(pad, self._nvidia_dual4k_supported))
        if resolution == UHD_4K and not dual4k_supported:
            reason = self._dual4k_reason_by_padding.get(pad) or self._nvidia_dual4k_reason or "Wybrany koder nie przeszedł testu Podwójnego 4K."
            self.options_data["comparison_resolution"] = FULL_HD
            OptionsDialog.save_resolution(FULL_HD)
            QMessageBox.information(
                self, I18n.tr("resolution_fallback_title"),
                I18n.tr("resolution_fallback_message").format(reason=reason),
            )
            return
        self.options_data["comparison_resolution"] = resolution
        OptionsDialog.save_resolution(resolution)

    def load_video1(self):
        path, _ = QFileDialog.getOpenFileName(self, I18n.tr("load_video1_title"), "", "MP4 (*.mp4)")
        if not path:
            return
        print("Video 1:", path)
        self._start_telemetry(1, path)
        self.player1.setSource(QUrl.fromLocalFile(path))
        self._manual_offset = False
        self._preview_sync.play()
        self.player1.set_overlay("")
        self._refresh_nvidia_export_modes()
        self._recalc_sync_offset()

    def load_video2(self):
        path, _ = QFileDialog.getOpenFileName(self, I18n.tr("load_video2_title"), "", "MP4 (*.mp4)")
        if not path:
            return
        print("Video 2:", path)
        self._start_telemetry(2, path)
        self.player2.setSource(QUrl.fromLocalFile(path))
        self._manual_offset = False
        self._preview_sync.play()
        self.player2.set_overlay("")
        self._recalc_sync_offset()
        self._connect_sync()
        self._refresh_nvidia_export_modes()

    def _start_telemetry(self, index, path):
        previous = self._telemetry_jobs.get(index)
        if previous:
            previous.set()
        cancel = threading.Event()
        self._telemetry_jobs[index] = cancel
        setattr(self, f'telemetry{index}', NullTelemetry(path))
        self.btn_export.setEnabled(False)

        def load():
            provider, error = None, None
            try:
                provider = create_telemetry(path, cancel_event=cancel)
            except Exception as exc:
                error = str(exc)
            self._telemetry_results.put((index, cancel, provider, error))

        threading.Thread(target=load, daemon=True).start()

    def _poll_telemetry(self):
        while not self._telemetry_results.empty():
            index, cancel, provider, error = self._telemetry_results.get_nowait()
            if self._telemetry_jobs.get(index) is not cancel:
                continue  # a different file has already replaced this job
            del self._telemetry_jobs[index]
            if provider is not None:
                setattr(self, f'telemetry{index}', provider)
            if error:
                print(f'Telemetry: {error}')
                QMessageBox.warning(self, 'Telemetria', error)
            self._recalc_sync_offset()
            if not self._telemetry_jobs:
                self.btn_export.setEnabled(True)

    def closeEvent(self, event):
        for cancel in self._telemetry_jobs.values():
            cancel.set()
        super().closeEvent(event)

    def _recalc_sync_offset(self):
        """Calculate time-based sync offset between the two videos using
        GPMF absolute datetime (GPSU or creation_time).

        offset_ms = datetime(film2_start) - datetime(film1_start)
        Positive offset means film2 started later → player2 trails player1.
        """
        if self._manual_offset:
            return
        if self.telemetry1 is None or self.telemetry2 is None:
            self._sync_offset_ms = 0
            return

        dt1 = self.telemetry1.get_datetime_at(0)
        dt2 = self.telemetry2.get_datetime_at(0)

        if dt1 is not None and dt2 is not None:
            self._sync_offset_ms = int((dt2 - dt1).total_seconds() * 1000)
            try:
                dt1_local = dt1.astimezone()
                dt2_local = dt2.astimezone()
            except Exception:
                dt1_local = dt1
                dt2_local = dt2
            print(I18n.tr("time_sync_offset", ms=self._sync_offset_ms, 
                          dt2=dt2_local.strftime('%H:%M:%S.%f')[:-3], 
                          dt1=dt1_local.strftime('%H:%M:%S.%f')[:-3]))
        else:
            self._sync_offset_ms = 0
            print(I18n.tr("no_time_sync"))

        self._preview_sync.set_offset(self._sync_offset_ms)

    def _connect_sync(self):
        pass  # Monotonic timeline owns synchronization; no signal disconnect.

    def _auto_sync(self):
        """Synchronizuj oba filmy przez korelację audio z filtracją szumu wiatru.

        Szum wiatru jest głównie poniżej 500 Hz – filtr górnoprzepustowy
        usuwa go, pozostawiając charakterystyczne dźwięki (przerzutki,
        hamulce, nawierzchnia), które są unikalne dla danego momentu.
        """
        if not self.telemetry1 or not self.telemetry2:
            QMessageBox.warning(self, I18n.tr("btn_autosync"), I18n.tr("autosync_load_videos"))
            return

        try:
            import numpy as np
        except ImportError:
            QMessageBox.warning(
                self, I18n.tr("btn_autosync"),
                I18n.tr("autosync_no_numpy")
            )
            return

        self.btn_autosync.setEnabled(False)
        self.btn_autosync.setText(I18n.tr("autosync_loading_1"))
        QApplication.processEvents()

        try:
            SR = 22050        # częstotliwość próbkowania
            MAX_SEC = 120     # pierwsze 120s

            def extract_audio(path: str) -> np.ndarray:
                from video_encoder import resolve_legacy_ffmpeg
                cmd = [
                    resolve_legacy_ffmpeg("CPU"), "-y",
                    "-t", str(MAX_SEC),
                    "-i", path,
                    "-ac", "1",
                    "-ar", str(SR),
                    "-f", "f32le",
                    "-",
                ]
                p = subprocess.run(cmd, capture_output=True, timeout=300)
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.decode("utf-8", errors="replace")[:500])
                return np.frombuffer(p.stdout, dtype=np.float32).copy()

            audio1 = extract_audio(self.telemetry1.filename)
            
            self.btn_autosync.setText(I18n.tr("autosync_loading_2"))
            QApplication.processEvents()
            
            audio2 = extract_audio(self.telemetry2.filename)

            self.btn_autosync.setText(I18n.tr("autosync_analyzing"))
            QApplication.processEvents()

            if len(audio1) < 1000 or len(audio2) < 1000:
                raise RuntimeError(I18n.tr("autosync_short_audio"))

            # ------------------------------------------------------------
            # Filtr górnoprzepustowy – usuwa szum wiatru (niske częstotl.)
            # ------------------------------------------------------------
            try:
                from scipy import signal as scipy_signal
                cutoff_hz = 500
                nyquist = 0.5 * SR
                norm_cutoff = cutoff_hz / nyquist
                b, a = scipy_signal.butter(4, norm_cutoff, btype='high')
                audio1 = scipy_signal.filtfilt(b, a, audio1)
                audio2 = scipy_signal.filtfilt(b, a, audio2)
                print(I18n.tr("autosync_scipy", cutoff=cutoff_hz))
            except ImportError:
                # Fallback: odejmij średnią kroczącą (prosty HP)
                window = int(SR * 0.01)  # 10 ms
                kernel = np.ones(window) / window
                audio1 = audio1 - np.convolve(audio1, kernel, mode='same')
                audio2 = audio2 - np.convolve(audio2, kernel, mode='same')
                print(I18n.tr("autosync_no_scipy"))

            # ------------------------------------------------------------
            # Korelacja krzyżowa (FFT) na obwiedni sygnału (Envelope)
            # ------------------------------------------------------------
            # Aby precyzyjniej zsynchronizować nagrania pełne stukotów i wiatru,
            # korelujemy obwiednię amplitudy (zamiast surowej fali, która traci fazę).
            
            # 1. Wartość bezwzględna po filtrze górnoprzepustowym
            env1 = np.abs(audio1)
            env2 = np.abs(audio2)
            
            # 2. Filtracja dolnoprzepustowa (wygładzenie obwiedni do np. 50 Hz)
            try:
                from scipy import signal as scipy_signal
                b_low, a_low = scipy_signal.butter(2, 50 / (0.5 * SR), btype='low')
                env1 = scipy_signal.filtfilt(b_low, a_low, env1)
                env2 = scipy_signal.filtfilt(b_low, a_low, env2)
            except ImportError:
                window_env = int(SR * 0.02) # 20 ms
                kernel_env = np.ones(window_env) / window_env
                env1 = np.convolve(env1, kernel_env, mode='same')
                env2 = np.convolve(env2, kernel_env, mode='same')
                
            # 3. Decymacja (zmniejszenie częstotliwości próbkowania dla lepszej widoczności szczytów)
            ds_factor = 10
            env1 = env1[::ds_factor]
            env2 = env2[::ds_factor]
            new_SR = SR / ds_factor
            
            # Normalizacja do [0, 1]
            env1 /= np.max(env1) + 1e-10
            env2 /= np.max(env2) + 1e-10

            n = len(env1) + len(env2) - 1
            fft1 = np.fft.rfft(env1, n)
            fft2 = np.fft.rfft(env2, n)
            corr = np.fft.irfft(fft1 * np.conj(fft2))

            peak_idx = int(np.argmax(np.abs(corr)))
            
            # Obliczenie poprawnego przesunięcia w próbkach (cykliczność FFT)
            if peak_idx > n // 2:
                offset_samples_ds = peak_idx - n
            else:
                offset_samples_ds = peak_idx
                
            offset_sec = offset_samples_ds / new_SR

            self._sync_offset_ms = int(offset_sec * 1000)
            self._manual_offset = True
            self._preview_sync.set_offset(self._sync_offset_ms)

            print(I18n.tr("autosync_detected", sec=offset_sec, ms=self._sync_offset_ms))

            if abs(self._sync_offset_ms) > 500:
                direction = I18n.tr("autosync_later") if self._sync_offset_ms > 0 else I18n.tr("autosync_earlier")
                print(I18n.tr("autosync_movie2_starts", ms=abs(self._sync_offset_ms), direction=direction))
            else:
                print(I18n.tr("autosync_already_synced"))

            # Wymuś korektę na bieżącej pozycji


        except FileNotFoundError:
            QMessageBox.warning(self, I18n.tr("btn_autosync"), I18n.tr("autosync_no_ffmpeg"))
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, I18n.tr("btn_autosync"), I18n.tr("autosync_timeout"))
        except Exception as e:
            QMessageBox.warning(self, I18n.tr("btn_autosync"), I18n.tr("autosync_error", error=e))
        finally:
            self.btn_autosync.setEnabled(True)
            self.btn_autosync.setText(I18n.tr("btn_autosync"))

    def change_orientation(self):
        # Now handled by _build_seekbar_layout via signal
        pass

    def update_overlays(self):
        if self.chk_overlay.isChecked():
            if self.telemetry1 is not None:
                sec = self.player1.position() / 1000.0
                self.player1.set_overlay(self.telemetry1.get_overlay_text(sec))
            if self.telemetry2 is not None:
                sec = self.player2.position() / 1000.0
                self.player2.set_overlay(self.telemetry2.get_overlay_text(sec))
        else:
            self.player1.set_overlay("")
            self.player2.set_overlay("")

    def _on_overlay_toggled(self, state):
        self.update_overlays()

    def _set_export_controls_enabled(self, enabled: bool):
        self.btn_video1.setEnabled(enabled)
        self.btn_video2.setEnabled(enabled)
        self.layout_mode.setEnabled(enabled)
        self.audio_combo.setEnabled(enabled)
        self.decoder_combo.setEnabled(enabled)
        self.backend_combo.setEnabled(enabled)
        self.preset_combo.setEnabled(enabled)
        self.encoder_combo.setEnabled(enabled)
        self.bitrate_spin.setEnabled(enabled)
        self.scale_combo.setEnabled(enabled)
        self.btn_autosync.setEnabled(enabled)
        self.chk_overlay.setEnabled(enabled)
        self.shared_seekbar.setEnabled(enabled)
        self.seekbar1.setEnabled(enabled)
        self.seekbar2.setEnabled(enabled)
        self.btn_play.setEnabled(enabled)
        for btn in (self.btn_rev1, self.btn_fwd1, self.btn_rev2, self.btn_fwd2):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _cancel_export(self):
        self._cancel_requested = True
        self.export_preview.stop()
        if not self._export_process:
            self._on_export_finished(1, QProcess.NormalExit)
            return
        self.btn_export.setText(I18n.tr("export_cancelling"))
        self.btn_export.setEnabled(False)
        print("[export] Żądanie anulowania eksportu...")
        if self._active_backend == "d3d11":
            # Native exporter: main.cpp monitors stdin for "cancel" keyword → sets m_cancelRequested
            # → ExportPipeline flushes encoder, writes MP4 trailer, preserves partial file.
            try:
                self._export_process.write(b'cancel\n')
                self._export_process.waitForBytesWritten(500)
            except Exception as e:
                print(f"[export] Błąd zapisu do stdin: {e}")
        else:
            # Legacy FFmpeg: send "q\n" to stdin so FFmpeg stops encoding gracefully,
            # flushes buffers and writes the MP4 moov atom before exiting.
            try:
                self._export_process.write(b'q\n')
                self._export_process.waitForBytesWritten(500)
            except Exception as e:
                print(f"[export] Błąd zapisu do stdin Legacy: {e}")
        # Give native/ffmpeg up to 8 s to finalize the file before force-killing.
        process = self._export_process
        QTimer.singleShot(8000, lambda: process.kill() if self._export_process is process and process.state() != QProcess.NotRunning else None)


    def _force_kill_export(self):
        if self._export_process and self._export_process.state() != QProcess.ProcessState.NotRunning:
            print("[export] Wymuszone zakończenie procesu eksportu...")
            try:
                self._export_process.kill()
            except Exception:
                pass

    def enter_export_preview_mode(self) -> str:
        """Switch main viewing area to export live preview and start thumbnail IPC server."""
        self.player1.pause()
        self.player2.pause()
        self.preview_stack.setCurrentIndex(1)
        self.export_preview.layout().activate()
        return self.export_preview.start()

    def exit_export_preview_mode(self):
        """Restore main viewing area to normal dual player preview and stop thumbnail server."""
        self.preview_stack.setCurrentIndex(0)
        self.export_preview.stop()

    def export_video(self):
        if self._is_exporting:
            self._cancel_export()
            return
        if not self.telemetry1 or not self.telemetry2:
            QMessageBox.warning(self, I18n.tr('btn_export'), I18n.tr('export_load_videos'))
            return
        path, _ = QFileDialog.getSaveFileName(self, I18n.tr('export_save_title'), '', 'MP4 (*.mp4)')
        if not path:
            return
        self._export_started_at = None
        self._export_clicked_at = time.perf_counter()
        self._export_out_path = path
        self._cancel_requested = False
        self._last_gpu_metrics = None
        self._last_gpu_error = ''
        self._ffmpeg_log_path = None
        self._export_log = ''
        self._export_pending = ''
        self._process_error = ''
        self._preview_warning_seen = False
        self._active_backend = 'preparation'
        self._export_tmpdir = Path(tempfile.mkdtemp(prefix='komparator_export_'))
        self._is_exporting = True
        self._set_export_controls_enabled(False)
        self.btn_export.setText('Anuluj')

        preview_enabled = bool(self.options_data.get("preview_during_export", True))
        layout = 'left_right' if self.layout_mode.currentIndex() == 0 else 'top_bottom'
        pad_to_16_9 = bool(self.options_data.get("pad_to_16_9", True))
        resolution = self.options_data.get("comparison_resolution", FULL_HD)
        output_size = comparison_output_size(resolution, layout, pad_to_16_9)
        self._export_expected_size = output_size
        self._preview_warning_seen = False
        self._preview_failure_validation_pending = False
        if preview_enabled:
            preview_pipe = self.enter_export_preview_mode()
            preview_port = self.export_preview.preview_port
            preview_viewport = self.export_preview.image.size()
        else:
            self.player1.pause()
            self.player2.pause()
            preview_pipe = ""
            preview_port = 0
            preview_viewport = self.splitter.size()
        composition_size = comparison_output_size(resolution, layout, False)
        preview_size = choose_preview_size(preview_viewport, composition_size)
        print(f"[export] PREVIEW_SIZE={preview_size[0]}x{preview_size[1]} PREVIEW_FPS=5 VIDEO_VIEWPORT={preview_viewport.width()}x{preview_viewport.height()}")

        backend_idx = self.backend_combo.currentIndex() if hasattr(self, 'backend_combo') and self.backend_combo is not None else 0
        options = dict(export_preview=preview_enabled, preview_pipe=preview_pipe,
                       preview_port=preview_port, preview_size=preview_size, output=path,
                       playback_speed=int(self.scale_combo.currentData() or 1),
                       dual_4k=self.options_data.get("comparison_resolution", FULL_HD) == UHD_4K,
                       hw=self.encoder_combo.currentText(), preset=self.preset_combo.currentText(),
                       backend=backend_idx, bitrate=self.bitrate_spin.value(),
                       audio=['mute','left','right','both'][self.audio_combo.currentIndex()],
                       layout=layout,
                       offset=self._sync_offset_ms, overlay=self.chk_overlay.isChecked(),
                       overlay_font_scale=self.options_data.get("overlay_font_scale", 1.0),
                       overlay_opacity=self.options_data.get("overlay_opacity", 1.0),
                       pad_to_4k=pad_to_16_9,
                       pad_to_16_9=pad_to_16_9)
        providers, directory = (self.telemetry1, self.telemetry2), self._export_tmpdir
        def prepare():
            from export_prepare import prepare_export
            try:
                result = prepare_export(options, providers, directory)
                self._export_results.put((result, None))
            except Exception as exc:
                self._export_results.put((None, str(exc)))
        threading.Thread(target=prepare, daemon=True).start()

    def _poll_export_preparation(self):
        if self._export_results.empty():
            return
        result, error = self._export_results.get_nowait()
        if error or self._cancel_requested:
            self._process_error = error or 'Cancelled during preparation'
            self._on_export_finished(1, QProcess.NormalExit)
            return
        if len(result) == 5:
            self._active_backend, program, args, self._export_duration, self._backend_selected = result
        else:
            self._active_backend, program, args, self._export_duration = result
            self._backend_selected = self._active_backend.upper()
        if self._backend_selected == "NVIDIA_MODERN_FFMPEG":
            self._ffmpeg_log_path = str(Path(self._export_out_path).with_suffix(".ffmpeg.log"))
            command_line = subprocess.list2cmdline([program or "", *args])
            try:
                Path(self._ffmpeg_log_path).write_text(
                    f"FFMPEG_COMMAND={command_line}\n\n", encoding="utf-8"
                )
                print(f"[export] NVIDIA_MODERN_LOG={self._ffmpeg_log_path}")
            except OSError as exc:
                print(f"[export] Nie można utworzyć logu FFmpeg: {exc}")
                self._ffmpeg_log_path = None
        if self._active_backend != 'd3d11':
            self.export_preview.image.setText("Trwa eksport FFmpeg...")
            self.export_preview.status.setText(f"Backend: {self._backend_selected}")
        self._start_export_process(program, args)

    def _start_export_process(self, program, args):
        self._export_process = QProcess(self)
        self._export_process.setProcessChannelMode(QProcess.MergedChannels)
        self._export_process.started.connect(self._on_export_started)
        self._export_process.errorOccurred.connect(self._on_export_process_error)
        self._export_process.readyReadStandardOutput.connect(self._on_export_output)
        self._export_process.finished.connect(self._on_export_finished)
        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self._export_process.start(program or "", args)

    def _on_export_started(self):
        self._export_started_at = time.perf_counter()
        self._export_start_latency = self._export_started_at - self._export_clicked_at
        print(f'[export] backend={self._active_backend} process started after {self._export_start_latency:.3f}s')

    def _on_export_process_error(self, error):
        if not self._export_process:
            return
        self._process_error = f'{error.name}: {self._export_process.errorString()}'
        self._on_export_output()
        if error == QProcess.FailedToStart:
            self._on_export_finished(-1, QProcess.CrashExit)

    def _on_export_output(self):
        if not self._export_process:
            return
        data = self._export_process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._export_log += data
        if data and getattr(self, "_ffmpeg_log_path", None):
            try:
                with open(self._ffmpeg_log_path, "a", encoding="utf-8", errors="replace") as log:
                    log.write(data)
            except OSError as exc:
                print(f"[export] Nie można dopisać do logu FFmpeg: {exc}")
        self._export_pending += data.replace("\r", "\n")
        lines = self._export_pending.split("\n")
        self._export_pending = lines.pop()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            preview_sink_error = (
                ("out#1/fifo" in line.lower() or "vost#1:" in line.lower())
                and any(word in line.lower() for word in ("error", "failed", "terminating thread"))
            )
            if (self._active_backend == "legacy" and not self._preview_warning_seen
                    and preview_sink_error):
                self._preview_warning_seen = True
                self.export_preview.mark_tcp_preview_unavailable()
            if self._active_backend == "d3d11" and line.startswith("{") and line.endswith("}"):
                try:
                    msg = json.loads(line)
                    mtype = msg.get("type")
                    if mtype == "progress":
                        pct = int(msg.get("percent", 0))
                        frame = msg.get("frame", 0)
                        fps = msg.get("fps", 0.0)
                        eta = msg.get("eta", 0.0)
                        eta_m = int(eta) // 60
                        eta_s = int(eta) % 60
                        self.export_progress.setValue(pct)
                        self.export_progress.setFormat(f"D3D11 Zero-Copy {pct}% | kl.{frame} | {fps:.1f}fps | ETA {eta_m}:{eta_s:02d}")
                        self.export_preview.status.setText(self.export_progress.format())
                        self.btn_export.setText(f"Anuluj ({pct}%)")
                    elif mtype == "complete":
                        self._last_gpu_metrics = msg
                    elif mtype == "warning" and "PREVIEW_DISABLED_AFTER_ERROR" in msg.get("message", ""):
                        self.export_preview.status.setText(msg["message"])
                        self.export_preview.stop()
                    elif mtype == "error":
                        self._last_gpu_error += json.dumps(msg, ensure_ascii=False) + "\n"
                except Exception:
                    pass
            elif self._active_backend == "legacy" and line.startswith("frame="):
                m_frame = re.search(r"frame=\s*(\d+)", line)
                m_fps = re.search(r"fps=\s*([\d.]+)", line)
                m_time = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
                m_speed = re.search(r"speed=\s*([\d.]+)x", line)

                pct = 0
                sec = 0.0
                if m_time:
                    h, m, s, cs = m_time.groups()
                    sec = int(h) * 3600 + int(m) * 60 + int(s) + float("0." + cs)
                    pct = int(sec / self._export_duration * 100) if self._export_duration else 0

                eta_str = ""
                if m_speed and m_time:
                    try:
                        speed_val = float(m_speed.group(1))
                        if speed_val > 0.01:
                            remaining_sec = max(0.0, self._export_duration - sec)
                            eta_total_sec = int(remaining_sec / speed_val)
                            eta_m = eta_total_sec // 60
                            eta_s = eta_total_sec % 60
                            eta_str = f" | ETA {eta_m}:{eta_s:02d}"
                    except Exception:
                        pass

                frame = m_frame.group(1) if m_frame else "0"
                fps = m_fps.group(1) if m_fps else "0"
                bname = getattr(self, "_backend_selected", "Legacy")
                self.export_progress.setValue(pct)
                self.export_progress.setFormat(f"{bname} {pct}% | kl.{frame} | {fps}fps{eta_str}")
                status = self.export_progress.format()
                if self.export_preview.preview_warning:
                    status += "\n" + self.export_preview.preview_warning
                self.export_preview.status.setText(status)
                self.btn_export.setText(f"Anuluj ({pct}%)")

    def _poll_preview_failure_validation(self):
        if self._preview_failure_validation_results.empty():
            return
        valid, detail, exit_code, exit_status = self._preview_failure_validation_results.get_nowait()
        self._preview_failure_validation_pending = False
        if valid:
            print(f"[export] PREVIEW_FAILURE_ISOLATED=1 MP4_VALIDATION=PASS {detail}")
            self._preview_warning_seen = True
            self._on_export_finished(0, QProcess.NormalExit, preview_failure_checked=True)
        else:
            self._process_error = f"Błąd wyjścia podglądu; MP4 nie przeszło walidacji: {detail}"
            print(f"[export] PREVIEW_FAILURE_ISOLATED=0 MP4_VALIDATION=FAIL {detail}")
            self._on_export_finished(exit_code, exit_status, preview_failure_checked=True)

    def _begin_preview_failure_validation(self, exit_code, exit_status):
        if self._preview_failure_validation_pending:
            return
        self._preview_failure_validation_pending = True
        self._is_exporting = True
        self.export_progress.setVisible(True)
        self.export_progress.setFormat("Podgląd utracony — sprawdzam zapisany plik MP4…")
        self.export_preview.mark_tcp_preview_unavailable()
        self.export_preview.status.setText("Podgląd niedostępny; trwa weryfikacja głównego eksportu.")
        self.exit_export_preview_mode()
        proc, self._export_process = self._export_process, None
        if proc:
            proc.deleteLater()
        output_path = self._export_out_path
        expected_size = self._export_expected_size
        expected_duration = float(self._export_duration or 0.0)
        hw = self.encoder_combo.currentText()
        from video_encoder import resolve_legacy_ffprobe
        ffprobe = resolve_legacy_ffprobe(hw)

        def validate():
            try:
                from export_result import validate_completed_mp4
                result = validate_completed_mp4(
                    ffprobe, output_path, expected_size, expected_duration, timeout=30,
                )
                self._preview_failure_validation_results.put((True, result, exit_code, exit_status))
            except Exception as exc:
                self._preview_failure_validation_results.put((False, str(exc), exit_code, exit_status))

        threading.Thread(target=validate, name="ComparatorPreviewFailureValidation", daemon=True).start()

    def _on_export_finished(self, exit_code, exit_status, preview_failure_checked=False):
        proc = self._export_process
        self._on_export_output()
        if self._export_pending:
            self._export_log += "\n"
            pending = self._export_pending
            self._export_pending = ""
            try:
                message = json.loads(pending)
                if message.get("type") == "complete":
                    self._last_gpu_metrics = message
                elif message.get("type") == "error":
                    self._last_gpu_error += pending
            except ValueError:
                pass
        if not preview_failure_checked and exit_code != 0 and not self._cancel_requested:
            from export_result import is_preview_only_failure
            if is_preview_only_failure(self._export_log, cancelled=self._cancel_requested):
                self._begin_preview_failure_validation(exit_code, exit_status)
                return
        self._export_process = None
        self._is_exporting = False
        self.exit_export_preview_mode()
        self._set_export_controls_enabled(True)

        if self._export_tmpdir:
            shutil.rmtree(self._export_tmpdir, ignore_errors=True)
            self._export_tmpdir = None

        self.btn_export.setText(I18n.tr("btn_export"))
        self.btn_export.setEnabled(True)
        self.export_progress.setVisible(False)

        if self._cancel_requested:
            QMessageBox.information(self, I18n.tr("btn_export"), I18n.tr("export_cancelled"))
        elif self._active_backend == "preparation":
            err = f"Błąd przygotowania eksportu:\n{self._process_error}"
            QMessageBox.critical(self, I18n.tr('btn_export'), err)
        elif (exit_code == 0 and exit_status == QProcess.NormalExit and not self._process_error
              and not self._last_gpu_error and (self._active_backend != 'd3d11' or
              (self._last_gpu_metrics and self._last_gpu_metrics.get('status') == 'success'))):
            if self._active_backend == "d3d11" and self._last_gpu_metrics:
                m = self._last_gpu_metrics
                msg = I18n.tr(
                    "export_ready_gpu",
                    path=self._export_out_path,
                    frames=m.get("total_frames", 0),
                    fps=m.get("avg_fps", 0.0),
                    dur=m.get("duration", 0.0),
                    hwdown=m.get("full_frame_hwdownload_count", 0),
                    hwup=m.get("full_frame_hwupload_count", 0),
                    sw=m.get("software_frame_count", 0),
                    tel_count=m.get("telemetry_texture_uploads", 0),
                    tel_kb=m.get("telemetry_uploaded_bytes", 0) // 1024,
                )
                QMessageBox.information(self, I18n.tr("btn_export"), msg)
            else:
                QMessageBox.information(self, I18n.tr("btn_export"), I18n.tr("export_ready", path=self._export_out_path))
        else:
            native_err = self._last_gpu_error or ("no success completion received" if self._active_backend == "d3d11" else "none")
            tail = '\n'.join(self._export_log.splitlines()[-15:])[-3000:]
            backend_name = getattr(self, "_backend_selected", self._active_backend)
            err = (f'backend={backend_name} (process={self._active_backend})\n'
                   f'exit code={exit_code}\nexit status={exit_status.name}\n'
                   f'process error={self._process_error or "none"}\n'
                   f'native error={native_err}\n'
                   f'FFmpeg log={getattr(self, "_ffmpeg_log_path", None) or "none"}\n{tail}')
            QMessageBox.critical(self, I18n.tr('btn_export'), err)
        if proc:
            proc.deleteLater()



if __name__ == "__main__":
    _check_deps()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1400, 800)
    window.show()
    sys.exit(app.exec())
