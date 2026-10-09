"""Options dialog for Comparator.

Allows configuring:
1. Overlay text size (50% - 200%)
2. Overlay text opacity (0% - 100%)
3. Comparison output resolution
Persists options in QSettings.
"""
from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QCheckBox, QPushButton, QGroupBox, QFrame, QRadioButton, QButtonGroup
)
from i18n import I18n

FULL_HD = "2160p"
UHD_4K = "dual4k"


def comparison_output_size(resolution: str, layout: str, pad_to_4k: bool = True) -> tuple[int, int]:
    """Return the final output canvas dimensions."""
    if pad_to_4k:
        return (7680, 4320) if resolution == UHD_4K else (3840, 2160)
    if resolution == UHD_4K:
        return (7680, 2160) if layout == "left_right" else (3840, 4320)
    return (3840, 1080) if layout == "left_right" else (1920, 2160)


class OptionsDialog(QDialog):
    settingsApplied = Signal(float, float, bool)
    comparisonResolutionApplied = Signal(str)

    def __init__(self, parent=None, on_preview_change=None, *, active_resolution=None,
                 resolution_available=False, resolution_reason="", layout="left_right",
                 resolution_availability_by_padding=None, resolution_reason_by_padding=None):
        super().__init__(parent)
        self.setWindowTitle(I18n.tr("options_title"))
        self.setModal(True)
        self.setMinimumWidth(500)
        self.on_preview_change = on_preview_change
        self.resolution_availability_by_padding = resolution_availability_by_padding or {}
        self.resolution_reason_by_padding = resolution_reason_by_padding or {}
        settings = self.load_settings()
        self.resolution_available = bool(
            self.resolution_availability_by_padding.get(settings["pad_to_16_9"], resolution_available)
        )
        self.resolution_reason = resolution_reason or I18n.tr("resolution_unavailable_default")
        self.layout_name = layout

        self.initial_font_scale = settings["overlay_font_scale"]
        self.initial_opacity = settings["overlay_opacity"]
        self.initial_pad_to_4k = settings["pad_to_16_9"]
        requested_resolution = active_resolution or settings["comparison_resolution"]
        self.initial_resolution = requested_resolution if requested_resolution in (FULL_HD, UHD_4K) else FULL_HD
        if self.initial_resolution == UHD_4K and not self.resolution_available:
            self.initial_resolution = FULL_HD

        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(16, 16, 16, 16)

        # --- Overlay group ---
        grp_overlay = QGroupBox(I18n.tr("chk_overlay"))
        ov_layout = QVBoxLayout(grp_overlay)
        ov_layout.setSpacing(12)

        # 1. Font size slider (50% - 200%)
        lbl_font = QLabel(I18n.tr("overlay_font_size_label"))
        lbl_font.setToolTip(I18n.tr("overlay_font_size_tooltip"))
        ov_layout.addWidget(lbl_font)

        row_font = QHBoxLayout()
        self.slider_font = QSlider(Qt.Horizontal)
        self.slider_font.setRange(50, 200)
        self.slider_font.setSingleStep(5)
        self.slider_font.setValue(int(round(self.initial_font_scale * 100)))
        self.slider_font.setToolTip(I18n.tr("overlay_font_size_tooltip"))

        self.val_font = QLabel(f"{self.slider_font.value()}%")
        self.val_font.setFixedWidth(50)
        self.slider_font.valueChanged.connect(self._on_font_changed)

        row_font.addWidget(self.slider_font, 1)
        row_font.addWidget(self.val_font)
        ov_layout.addLayout(row_font)

        # 2. Opacity slider (0% - 100%)
        lbl_opacity = QLabel(I18n.tr("overlay_opacity_label"))
        lbl_opacity.setToolTip(I18n.tr("overlay_opacity_tooltip"))
        ov_layout.addWidget(lbl_opacity)

        row_op = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setSingleStep(5)
        self.slider_opacity.setValue(int(round(self.initial_opacity * 100)))
        self.slider_opacity.setToolTip(I18n.tr("overlay_opacity_tooltip"))

        self.val_opacity = QLabel(f"{self.slider_opacity.value()}%")
        self.val_opacity.setFixedWidth(50)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)

        row_op.addWidget(self.slider_opacity, 1)
        row_op.addWidget(self.val_opacity)
        ov_layout.addLayout(row_op)

        root.addWidget(grp_overlay)

        # --- Video formatting group ---
        grp_video = QGroupBox(I18n.tr("app_title"))
        vid_layout = QVBoxLayout(grp_video)

        self.grp_resolution = QGroupBox(I18n.tr("resolution_group"))
        resolution_layout = QVBoxLayout(self.grp_resolution)
        resolution_layout.setSpacing(4)
        self.resolution_buttons = QButtonGroup(self)
        self.radio_full_hd = QRadioButton(I18n.tr("resolution_full_hd"))
        self.radio_4k_uhd = QRadioButton(I18n.tr("resolution_4k_uhd"))
        self.radio_full_hd.setObjectName("resolution_full_hd")
        self.radio_4k_uhd.setObjectName("resolution_4k_uhd")
        self.resolution_buttons.addButton(self.radio_full_hd)
        self.resolution_buttons.addButton(self.radio_4k_uhd)
        self.radio_4k_uhd.setEnabled(self.resolution_available)
        self.radio_4k_uhd.setToolTip(self.resolution_reason if not self.resolution_available else "")
        self.radio_full_hd.setChecked(self.initial_resolution == FULL_HD)
        self.radio_4k_uhd.setChecked(self.initial_resolution == UHD_4K)
        resolution_layout.addWidget(self.radio_full_hd)
        resolution_layout.addWidget(self.radio_4k_uhd)
        self.lbl_resolution_status = QLabel()
        self.lbl_resolution_status.setWordWrap(True)
        self.lbl_resolution_status.setObjectName("resolution_status")
        resolution_layout.addWidget(self.lbl_resolution_status)
        self.lbl_output_dimensions = QLabel()
        self.lbl_output_dimensions.setWordWrap(True)
        self.lbl_output_dimensions.setObjectName("output_dimensions")
        resolution_layout.addWidget(self.lbl_output_dimensions)
        self.chk_pad_16_9 = QCheckBox(I18n.tr("pad_to_16_9_label"))
        self.chk_pad_16_9.setObjectName("pad_to_16_9")
        self.chk_pad_16_9.setToolTip(I18n.tr("pad_to_16_9_tooltip"))
        self.chk_pad_16_9.setChecked(self.initial_pad_to_4k)
        resolution_layout.addWidget(self.chk_pad_16_9)
        self.chk_pad_16_9.toggled.connect(self._update_resolution_state)
        self.radio_full_hd.toggled.connect(self._update_resolution_state)
        self.radio_4k_uhd.toggled.connect(self._update_resolution_state)
        vid_layout.addWidget(self.grp_resolution)

        root.addWidget(grp_video)

        self.grp_preview = QGroupBox(I18n.tr("preview_group"))
        preview_layout = QVBoxLayout(self.grp_preview)
        self.chk_export_preview = QCheckBox(I18n.tr("preview_during_export_label"))
        self.chk_export_preview.setObjectName("preview_during_export")
        self.chk_export_preview.setChecked(settings["preview_during_export"])
        preview_layout.addWidget(self.chk_export_preview)
        root.addWidget(self.grp_preview)

        # --- Separator line ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # --- Buy coffee link row ---
        coffee_row = QHBoxLayout()
        coffee_row.setSpacing(6)
        self.lbl_coffee_prompt = QLabel(I18n.tr("buy_coffee_prompt"))
        self.lbl_coffee_link = QLabel(f'<a href="{I18n.tr("buy_coffee_url")}">{I18n.tr("buy_coffee_url")}</a>')
        self.lbl_coffee_link.setOpenExternalLinks(True)
        self.lbl_coffee_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.lbl_coffee = self.lbl_coffee_link
        coffee_row.addWidget(self.lbl_coffee_prompt)
        coffee_row.addWidget(self.lbl_coffee_link)
        coffee_row.addStretch()
        root.addLayout(coffee_row)

        # --- Button Box ---
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_ok = QPushButton(I18n.tr("btn_ok"))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_accept)

        self.btn_cancel = QPushButton(I18n.tr("btn_cancel"))
        self.btn_cancel.clicked.connect(self._on_reject)

        btn_box.addWidget(self.btn_ok)
        btn_box.addWidget(self.btn_cancel)
        root.addLayout(btn_box)
        self._update_resolution_state()
        self.adjustSize()

    @classmethod
    def load_settings(cls) -> dict:
        """Load persistent settings from QSettings with safe defaults."""
        s = QSettings("Comparator", "Comparator")
        stale_notification_keys = ("ntfy_enabled", "ntfy_server", "ntfy_topic")
        stale_settings_found = False
        for key in stale_notification_keys:
            if s.contains(key):
                s.remove(key)
                stale_settings_found = True
        if s.contains("preview_scaling_mode"):
            s.remove("preview_scaling_mode")
            stale_settings_found = True
        if stale_settings_found:
            s.sync()
        try:
            font_scale = float(s.value("overlay_font_scale", 1.0))
            if not (0.2 <= font_scale <= 3.0):
                font_scale = 1.0
        except Exception:
            font_scale = 1.0

        try:
            opacity = float(s.value("overlay_opacity", 1.0))
            if not (0.0 <= opacity <= 1.0):
                opacity = 1.0
        except Exception:
            opacity = 1.0

        def read_bool(key, default):
            value = s.value(key, default)
            return value.lower() in ("true", "1", "yes") if isinstance(value, str) else bool(value)

        pad_to_4k = read_bool("pad_to_16_9", True)

        comparison_resolution = str(s.value("comparison_resolution", FULL_HD) or FULL_HD).lower()
        if comparison_resolution in ("4k", "uhd", "dual4k", "dual_4k", "4k_uhd"):
            comparison_resolution = UHD_4K
        else:
            comparison_resolution = FULL_HD

        try:
            playback_speed = int(s.value("playback_speed", 1))
        except (TypeError, ValueError):
            playback_speed = 1
        if playback_speed not in (1, 2, 4):
            playback_speed = 1

        return {
            "overlay_font_scale": font_scale,
            "overlay_opacity": opacity,
            "pad_to_4k": pad_to_4k,
            "pad_to_16_9": pad_to_4k,
            "preview_during_export": read_bool("preview_during_export", True),
            "comparison_resolution": comparison_resolution,
            "playback_speed": playback_speed,
        }

    @classmethod
    def save_settings(cls, font_scale: float, opacity: float, pad_to_4k: bool, comparison_resolution=None,
                      *, preview_during_export=True):
        """Save settings to QSettings."""
        s = QSettings("Comparator", "Comparator")
        s.setValue("overlay_font_scale", float(font_scale))
        s.setValue("overlay_opacity", float(opacity))
        s.setValue("pad_to_16_9", bool(pad_to_4k))
        s.setValue("preview_during_export", bool(preview_during_export))
        s.remove("preview_scaling_mode")
        if comparison_resolution is not None:
            s.setValue("comparison_resolution", comparison_resolution if comparison_resolution == UHD_4K else FULL_HD)
        s.sync()

    @classmethod
    def save_resolution(cls, comparison_resolution: str):
        s = QSettings("Comparator", "Comparator")
        s.setValue("comparison_resolution", comparison_resolution if comparison_resolution == UHD_4K else FULL_HD)
        s.sync()

    @property
    def selected_resolution(self) -> str:
        return UHD_4K if self.radio_4k_uhd.isChecked() else FULL_HD

    def set_layout(self, layout: str):
        self.layout_name = layout
        self._update_resolution_state()

    def _update_resolution_state(self, *_args):
        pad = self.chk_pad_16_9.isChecked()
        available = bool(self.resolution_availability_by_padding.get(pad, self.resolution_available))
        reason = self.resolution_reason_by_padding.get(pad, self.resolution_reason)
        self.radio_4k_uhd.setEnabled(available)
        self.resolution_available = available
        if not available and self.radio_4k_uhd.isChecked():
            self.radio_full_hd.setChecked(True)
        is_uhd = self.radio_4k_uhd.isChecked() and available
        if available:
            self.lbl_resolution_status.setText("")
        else:
            self.lbl_resolution_status.setText(I18n.tr("resolution_unavailable").format(reason=reason))
        width, height = comparison_output_size(
            UHD_4K if is_uhd else FULL_HD, self.layout_name,
            pad,
        )
        layout_label = I18n.tr("layout_lr") if self.layout_name == "left_right" else I18n.tr("layout_ud")
        self.lbl_output_dimensions.setText(
            I18n.tr("resolution_output_dimensions").format(layout=layout_label, width=width, height=height)
        )

    def _on_font_changed(self, val):
        self.val_font.setText(f"{val}%")
        if self.on_preview_change:
            self.on_preview_change(val / 100.0, self.slider_opacity.value() / 100.0)

    def _on_opacity_changed(self, val):
        self.val_opacity.setText(f"{val}%")
        if self.on_preview_change:
            self.on_preview_change(self.slider_font.value() / 100.0, val / 100.0)

    def _on_accept(self):
        font_scale = self.slider_font.value() / 100.0
        opacity = self.slider_opacity.value() / 100.0
        pad_to_4k = self.chk_pad_16_9.isChecked()
        resolution = self.selected_resolution

        self.save_settings(
            font_scale, opacity, pad_to_4k, resolution,
            preview_during_export=self.chk_export_preview.isChecked(),
        )
        self.settingsApplied.emit(font_scale, opacity, pad_to_4k)
        self.comparisonResolutionApplied.emit(resolution)
        self.accept()

    def _on_reject(self):
        # Revert live preview if changed
        if self.on_preview_change:
            self.on_preview_change(self.initial_font_scale, self.initial_opacity)
        self.reject()
