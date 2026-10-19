"""Live 800x480 SPL meter dashboard for a laptop or Raspberry Pi."""

from __future__ import annotations

import threading
import json
from datetime import datetime
from pathlib import Path
import time

import numpy as np
import pyqtgraph as pg
import sounddevice as sd
from PyQt5 import QtCore, QtGui, QtWidgets

from dsp import AudioDSP
from recording import AudioRecorder


class SPLDashboard(QtWidgets.QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.sample_rate = int(config["sample_rate"])
        self.chunk_size = int(config["chunk_size"])
        self.dsp = AudioDSP(
            self.sample_rate, float(config["p_ref"]), float(config["cal_factor"])
        )
        self.config.setdefault("uncalibrated_cal_factor", 1.0)
        self.weighting = str(config.get("weighting", "A")).upper()
        self.chart_mode = "FFT"
        self.time_response = str(config.get("time_response", "FAST")).upper()
        if self.time_response not in {"FAST", "SLOW", "IMPULSE"}:
            self.time_response = "FAST"
        self.config_path = Path(__file__).resolve().parent / "config.json"
        self.recordings_dir = Path(__file__).resolve().parent / "recordings"
        self.recorder = AudioRecorder(self.sample_rate)
        self._recording_started_at: float | None = None
        self._recorded_seconds = 0.0
        self._calibration_chunks: list[np.ndarray] = []
        self._calibration_active = False
        self._calibration_started_at: float | None = None
        self._calibration_reference_db = 94.0
        self._detector_power: float | None = None
        self._peak_min_hz = 20.0
        self._peak_max_hz = min(20000.0, self.sample_rate / 2)
        self._peak_frequency = 0.0
        self._peak_level = float("-inf")
        self._audio_lock = threading.Lock()
        self._latest_audio = np.zeros(self.chunk_size, dtype=np.float32)
        self._audio_error = ""
        self._pressure_square_sum = 0.0
        self._pressure_sample_count = 0
        self._max_spl = float("-inf")
        self._current_spl = 0.0
        self._time_axis = np.arange(self.chunk_size) / self.sample_rate
        self._time_signal = np.zeros(self.chunk_size, dtype=np.float32)
        self._has_audio = False
        self.audio_active = False
        self.audio_input = None

        self.setWindowTitle("SPL Meter | Sound Lab")
        self.setFixedSize(800, 480)
        self._build_ui()
        self._set_weighting(self.weighting)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._update_dashboard)
        self.timer.start()
        self.recording_timer = QtCore.QTimer(self)
        self.recording_timer.setInterval(250)
        self.recording_timer.timeout.connect(self._update_recording_status)
        self.calibration_timer = QtCore.QTimer(self)
        self.calibration_timer.setInterval(100)
        self.calibration_timer.timeout.connect(self._update_calibration_progress)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QMainWindow { background: #10191d; color: #edf3ef; }"
            "QWidget { color: #edf3ef; font-family: 'DejaVu Sans', sans-serif; }"
            "QPushButton { background: #233238; border: 1px solid #40545a;"
            " border-radius: 4px; padding: 8px; font-size: 13px; font-weight: 600; }"
            "QPushButton:checked { background: #1d776d; border-color: #55d5b0; }"
            "QPushButton:hover { border-color: #76dbc0; }"
            "QLabel#section { color: #92aaa9; font-size: 10px; font-weight: 700; }"
            "QLabel#metric { color: #a8bab9; font-size: 11px; }"
            "QLabel#metricValue { color: #f0f5ee; font-size: 20px; font-weight: 600; }"
            "QLabel#status { font-size: 9px; font-weight: 700; }"
        )

        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        left_panel = QtWidgets.QWidget()
        left_panel.setFixedWidth(218)
        left = QtWidgets.QVBoxLayout(left_panel)
        left.setContentsMargins(2, 2, 2, 2)
        left.setSpacing(7)

        title = QtWidgets.QLabel("SOUND LAB")
        title.setStyleSheet("color: #74ddbb; font-size: 15px; font-weight: 800;")
        left.addWidget(title)
        left.addWidget(self._section_label("SOUND PRESSURE LEVEL"))

        self.spl_value = QtWidgets.QLabel("--.-")
        self.spl_value.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.spl_value.setStyleSheet(
            "color: #f4f7ef; font-size: 51px; font-weight: 700;"
        )
        self.spl_unit = QtWidgets.QLabel(f"dB SPL {self.weighting}")
        self.spl_unit.setStyleSheet("color: #75d9b8; font-size: 13px; font-weight: 700;")
        left.addWidget(self.spl_value)
        left.addWidget(self.spl_unit)

        metrics = QtWidgets.QGridLayout()
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(2)
        metrics.addWidget(self._metric_label("LEQ"), 0, 0)
        metrics.addWidget(self._metric_label("MAX"), 0, 1)
        self.leq_value = self._metric_value()
        self.max_value = self._metric_value()
        metrics.addWidget(self.leq_value, 1, 0)
        metrics.addWidget(self.max_value, 1, 1)
        left.addLayout(metrics)

        left.addWidget(self._section_label("WEIGHTING"))
        weighting_row = QtWidgets.QHBoxLayout()
        weighting_row.setSpacing(5)
        self.weight_buttons: dict[str, QtWidgets.QPushButton] = {}
        weighting_group = QtWidgets.QButtonGroup(self)
        weighting_group.setExclusive(True)
        for mode in ("A", "C", "Z"):
            button = QtWidgets.QPushButton(mode)
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.setChecked(mode == self.weighting)
            button.clicked.connect(lambda checked, value=mode: self._set_weighting(value))
            weighting_group.addButton(button)
            weighting_row.addWidget(button)
            self.weight_buttons[mode] = button
        left.addLayout(weighting_row)

        left.addWidget(self._section_label("TIME RESPONSE"))
        response_row = QtWidgets.QHBoxLayout()
        response_row.setSpacing(4)
        self.response_buttons: dict[str, QtWidgets.QPushButton] = {}
        response_group = QtWidgets.QButtonGroup(self)
        response_group.setExclusive(True)
        for response in ("FAST", "SLOW", "IMPULSE"):
            button = QtWidgets.QPushButton(response)
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.setStyleSheet("font-size: 10px; padding: 4px;")
            button.clicked.connect(
                lambda checked, value=response: self._set_time_response(value)
            )
            response_group.addButton(button)
            response_row.addWidget(button)
            self.response_buttons[response] = button
        self.response_buttons[self.time_response].setChecked(True)
        left.addLayout(response_row)
        self.response_info = QtWidgets.QLabel()
        self.response_info.setObjectName("metric")
        left.addWidget(self.response_info)
        self._update_response_info()

        left.addWidget(self._section_label("SPECTRUM VIEW"))
        view_row = QtWidgets.QHBoxLayout()
        view_row.setSpacing(5)
        self.fft_button = QtWidgets.QPushButton("FFT")
        self.oct_button = QtWidgets.QPushButton("1/3 OCT")
        self.fft_button.setCheckable(True)
        self.oct_button.setCheckable(True)
        self.fft_button.setChecked(True)
        view_group = QtWidgets.QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self.fft_button)
        view_group.addButton(self.oct_button)
        self.fft_button.clicked.connect(lambda: self._set_chart_mode("FFT"))
        self.oct_button.clicked.connect(lambda: self._set_chart_mode("OCT"))
        view_row.addWidget(self.fft_button)
        view_row.addWidget(self.oct_button)
        left.addLayout(view_row)

        self.reset_button = QtWidgets.QPushButton("RESET")
        self.reset_button.setMinimumHeight(38)
        self.reset_button.clicked.connect(self._reset_measurements)
        left.addWidget(self.reset_button)
        left.addStretch(1)
        self.status_label = QtWidgets.QLabel("INITIALIZING AUDIO")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)

        right_panel = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(7)
        self.time_plot = self._make_plot("TIME SIGNAL", "Time", "Amplitude")
        self.spectrum_plot = self._make_plot("SPECTRUM", "Frequency (Hz)", "Level (dB/Hz)")
        self.time_curve = self.time_plot.plot(pen=pg.mkPen("#60d8b4", width=1.4))
        self.spectrum_curve = self.spectrum_plot.plot(
            pen=pg.mkPen("#e9c46a", width=1.5)
        )
        self.oct_bars = pg.BarGraphItem(
            x=np.array([], dtype=np.float64),
            height=np.array([], dtype=np.float64),
            width=np.array([], dtype=np.float64),
            brush=pg.mkBrush("#e9c46a"),
        )
        self.spectrum_plot.addItem(self.oct_bars)
        self.oct_bars.hide()
        right.addWidget(self.time_plot, 1)
        right.addWidget(self.spectrum_plot, 1)

        root.addWidget(left_panel)
        root.addWidget(right_panel, 1)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabBar::tab { min-height: 34px; min-width: 118px; padding: 4px 10px;"
            " background: #233238; border: 1px solid #40545a; }"
            "QTabBar::tab:selected { background: #1d776d; color: #ffffff;"
            " border-bottom: 2px solid #74ddbb; }"
        )
        self.tabs.addTab(central, "測量")
        self.tabs.addTab(self._build_recording_page(), "錄音")
        self.tabs.addTab(self._build_analysis_page(), "頻譜分析")
        self.tabs.addTab(self._build_calibration_page(), "校正")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        app_central = QtWidgets.QWidget()
        app_layout = QtWidgets.QVBoxLayout(app_central)
        app_layout.setContentsMargins(8, 6, 8, 4)
        app_layout.setSpacing(5)
        app_layout.addWidget(self.tabs, 1)
        self.recording_status = QtWidgets.QLabel("● 未錄音")
        self.recording_status.setStyleSheet("color: #92aaa9; font-size: 10px;")
        app_layout.addWidget(self.recording_status)
        self.setCentralWidget(app_central)

    def _build_recording_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel("錄音與檔案播放")
        heading.setStyleSheet("font-size: 18px; font-weight: 700; color: #74ddbb;")
        layout.addWidget(heading)
        self.recording_page_status = QtWidgets.QLabel(
            "尚未錄音。錄音會使用目前麥克風的原始訊號。"
        )
        self.recording_page_status.setWordWrap(True)
        self.recording_page_status.setStyleSheet("color: #a8bab9;")
        layout.addWidget(self.recording_page_status)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(7)
        self.record_button = self._command_button("● 錄音", "#a83f49")
        self.pause_record_button = self._command_button("Ⅱ 暫停", "#725d32")
        self.stop_record_button = self._command_button("■ 停止", "#5b3940")
        self.save_record_button = self._command_button("存檔", "#285e58")
        self.play_file_button = self._command_button("▶ 播放選取", "#285e58")
        self.stop_playback_button = self._command_button("■ 停止播放", "#5b3940")
        for button in (
            self.record_button,
            self.pause_record_button,
            self.stop_record_button,
            self.save_record_button,
            self.play_file_button,
            self.stop_playback_button,
        ):
            controls.addWidget(button)
        layout.addLayout(controls)

        files_header = QtWidgets.QLabel("已儲存 WAV 錄音")
        files_header.setStyleSheet("font-weight: 700; color: #a8bab9;")
        layout.addWidget(files_header)
        self.recording_files = QtWidgets.QListWidget()
        self.recording_files.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.recording_files.itemDoubleClicked.connect(self._play_selected_recording)
        layout.addWidget(self.recording_files, 1)

        self.record_button.clicked.connect(self._start_recording)
        self.pause_record_button.clicked.connect(self._toggle_recording_pause)
        self.stop_record_button.clicked.connect(self._stop_recording)
        self.save_record_button.clicked.connect(self._save_recording)
        self.play_file_button.clicked.connect(self._play_selected_recording)
        self.stop_playback_button.clicked.connect(self._stop_playback)
        self._refresh_recordings()
        self._set_recording_controls("idle")
        return page

    def _build_analysis_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(7)

        heading = QtWidgets.QLabel("頻譜峰值與頻帶搜尋")
        heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #e9c46a;")
        layout.addWidget(heading)
        self.analysis_peak_label = QtWidgets.QLabel("Peak: -- Hz | -- dB/Hz")
        self.analysis_peak_label.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #f0e7bd;"
        )
        layout.addWidget(self.analysis_peak_label)

        self.analysis_plot = self._make_plot(
            "LIVE SPECTRUM / PEAK SEARCH", "Frequency (Hz)", "Level (dB/Hz)"
        )
        self.analysis_curve = self.analysis_plot.plot(
            pen=pg.mkPen("#e9c46a", width=1.5)
        )
        self.analysis_peak_marker = pg.ScatterPlotItem(
            size=9, brush=pg.mkBrush("#74ddbb"), pen=pg.mkPen("#10191d", width=1)
        )
        self.analysis_plot.addItem(self.analysis_peak_marker)
        layout.addWidget(self.analysis_plot, 1)

        band_controls = QtWidgets.QHBoxLayout()
        band_controls.setSpacing(6)
        band_title = QtWidgets.QLabel("搜尋頻帶 Hz")
        self.band_min_spin = self._frequency_spin(20.0, 20000.0, 20.0)
        self.band_max_spin = self._frequency_spin(20.0, 20000.0, 20000.0)
        self.band_fan_button = self._command_button("FAN", "#34434a")
        self.band_music_button = self._command_button("MUSIC", "#34434a")
        self.band_all_button = self._command_button("ALL", "#34434a")
        self.apply_band_button = self._command_button("套用頻帶", "#285e58")
        band_controls.addWidget(band_title)
        band_controls.addWidget(self.band_min_spin)
        band_controls.addWidget(QtWidgets.QLabel("至"))
        band_controls.addWidget(self.band_max_spin)
        band_controls.addWidget(self.band_fan_button)
        band_controls.addWidget(self.band_music_button)
        band_controls.addWidget(self.band_all_button)
        band_controls.addWidget(self.apply_band_button)
        layout.addLayout(band_controls)

        self.band_fan_button.clicked.connect(lambda: self._set_band_preset(60, 500))
        self.band_music_button.clicked.connect(lambda: self._set_band_preset(80, 12000))
        self.band_all_button.clicked.connect(lambda: self._set_band_preset(20, 20000))
        self.apply_band_button.clicked.connect(self._apply_peak_band)
        self._apply_peak_band()
        return page

    def _build_calibration_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel("A 加權聲壓校正")
        heading.setStyleSheet("font-size: 18px; font-weight: 700; color: #e9c46a;")
        layout.addWidget(heading)
        self.calibration_status = QtWidgets.QLabel()
        self.calibration_status.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(self.calibration_status)

        reference_row = QtWidgets.QHBoxLayout()
        reference_row.addWidget(QtWidgets.QLabel("參考聲級 (dB SPL)"))
        self.calibration_reference_spin = QtWidgets.QDoubleSpinBox()
        self.calibration_reference_spin.setRange(40.0, 130.0)
        self.calibration_reference_spin.setDecimals(1)
        self.calibration_reference_spin.setSingleStep(0.1)
        self.calibration_reference_spin.setValue(94.0)
        self.calibration_reference_spin.setSuffix(" dB")
        self.calibration_reference_spin.setMinimumHeight(42)
        reference_row.addWidget(self.calibration_reference_spin)
        reference_row.addStretch(1)
        layout.addLayout(reference_row)

        instructions = QtWidgets.QLabel(
            "使用穩定的 1 kHz 聲音與已知聲壓值。建議使用聲校正器（常見 94 dB SPL）；"
            "若用手機，必須先以已校正聲級計在麥克風位置量出實際 dB，單靠手機音量或頻率不能校正絕對 SPL。"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #c2ceca; font-size: 12px;")
        layout.addWidget(instructions)

        actions = QtWidgets.QHBoxLayout()
        self.start_calibration_button = self._command_button("開始 3 秒校正", "#806524")
        self.reset_calibration_button = self._command_button("重置校正", "#5b3940")
        actions.addWidget(self.start_calibration_button)
        actions.addWidget(self.reset_calibration_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.calibration_progress = QtWidgets.QProgressBar()
        self.calibration_progress.setRange(0, 100)
        self.calibration_progress.setValue(0)
        self.calibration_progress.setTextVisible(True)
        layout.addWidget(self.calibration_progress)
        layout.addStretch(1)

        self.start_calibration_button.clicked.connect(self._start_calibration)
        self.reset_calibration_button.clicked.connect(self._reset_calibration)
        self._update_calibration_status()
        return page

    @staticmethod
    def _command_button(text: str, color: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setMinimumHeight(44)
        button.setStyleSheet(
            f"QPushButton {{ background: {color}; border: 1px solid #53666a;"
            " border-radius: 4px; padding: 6px; font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { border-color: #edf3ef; }"
            "QPushButton:disabled { color: #83908e; background: #263034; }"
        )
        return button

    @staticmethod
    def _frequency_spin(minimum: float, maximum: float, value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(0)
        spin.setValue(value)
        spin.setSuffix(" Hz")
        spin.setMinimumHeight(38)
        spin.setMaximumWidth(112)
        return spin

    @staticmethod
    def _section_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("section")
        return label

    @staticmethod
    def _metric_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("metric")
        return label

    @staticmethod
    def _metric_value() -> QtWidgets.QLabel:
        label = QtWidgets.QLabel("--.- dB")
        label.setObjectName("metricValue")
        return label

    @staticmethod
    def _make_plot(title: str, x_label: str, y_label: str) -> pg.PlotWidget:
        plot = pg.PlotWidget(title=title)
        plot.setLabel("bottom", x_label)
        plot.setLabel("left", y_label)
        plot.showGrid(x=True, y=True, alpha=0.22)
        plot.setBackground("#10191d")
        plot.getPlotItem().titleLabel.setAttr("color", "#a7bfba")
        plot.getPlotItem().titleLabel.setAttr("size", "10pt")
        plot.getAxis("bottom").setTextPen("#9eb0ae")
        plot.getAxis("left").setTextPen("#9eb0ae")
        return plot

    def receive_audio(self, samples: np.ndarray, status: str = "") -> None:
        mono = np.asarray(samples, dtype=np.float32).copy()
        with self._audio_lock:
            self._latest_audio = mono
            self._audio_error = status
            self._has_audio = mono.size > 0
            if self._calibration_active and mono.size:
                self._calibration_chunks.append(mono.copy())
        self.recorder.add_audio(mono)

    def attach_audio_input(self, audio_input) -> None:
        self.audio_input = audio_input
        self.audio_active = audio_input.start()
        if self.audio_active:
            self.status_label.setText(f"MICROPHONE: {audio_input.device_name}")
            self.status_label.setStyleSheet("color: #56d6a0;")
        else:
            self._audio_error = audio_input.error or "No microphone input device found"
            self.status_label.setText("MICROPHONE UNAVAILABLE: check input device")
            self.status_label.setStyleSheet("color: #ff8c78;")

    def _set_weighting(self, mode: str) -> None:
        mode = mode.upper()
        if mode == self.weighting:
            self.weight_buttons[mode].setChecked(True)
            return
        self.weighting = mode
        self.weight_buttons[mode].setChecked(True)
        self.spl_unit.setText(f"dB SPL {mode}")
        self.dsp.reset_stream_filters()
        self._detector_power = None
        self._reset_measurements()

    def _set_time_response(self, response: str) -> None:
        self.time_response = response.upper()
        self.response_buttons[self.time_response].setChecked(True)
        self._detector_power = None
        self._update_response_info()

    def _update_response_info(self) -> None:
        descriptions = {
            "FAST": "125 ms",
            "SLOW": "1 s",
            "IMPULSE": "35 ms rise / 1.5 s fall",
        }
        if hasattr(self, "response_info"):
            self.response_info.setText(
                f"Detector: {self.time_response} ({descriptions[self.time_response]})"
            )

    def _set_chart_mode(self, mode: str) -> None:
        self.chart_mode = mode
        self.spectrum_plot.setTitle("SPECTRUM" if mode == "FFT" else "1/3 OCTAVE")
        self.spectrum_plot.setLabel(
            "left", "Level (dB/Hz)" if mode == "FFT" else "Band level (dB)"
        )
        self.spectrum_curve.setVisible(mode == "FFT")
        self.oct_bars.setVisible(mode == "OCT")

    def _reset_measurements(self) -> None:
        self._pressure_square_sum = 0.0
        self._pressure_sample_count = 0
        self._max_spl = float("-inf")
        self._detector_power = None
        self.leq_value.setText("--.- dB")
        self.max_value.setText("--.- dB")

    def _set_band_preset(self, minimum_hz: float, maximum_hz: float) -> None:
        self.band_min_spin.setValue(minimum_hz)
        self.band_max_spin.setValue(min(maximum_hz, self.sample_rate / 2))
        self._apply_peak_band()

    def _apply_peak_band(self) -> None:
        minimum_hz = self.band_min_spin.value()
        maximum_hz = self.band_max_spin.value()
        if minimum_hz >= maximum_hz:
            self.analysis_peak_label.setText("頻帶下限必須小於上限")
            return
        self._peak_min_hz = minimum_hz
        self._peak_max_hz = min(maximum_hz, self.sample_rate / 2)
        self.analysis_plot.setXRange(
            self._peak_min_hz,
            self._peak_max_hz,
            padding=0,
        )

    def _start_recording(self) -> None:
        if self.recorder.state in {"recording", "paused"}:
            return
        if not self.audio_active:
            self.recording_page_status.setText("目前沒有可用的麥克風輸入，無法錄音。")
            return
        self._stop_playback()
        self.recorder.start()
        self._recorded_seconds = 0.0
        self._recording_started_at = time.monotonic()
        self.recording_timer.start()
        self._set_recording_controls("recording")
        self._update_recording_status()

    def _toggle_recording_pause(self) -> None:
        if self.recorder.state == "recording":
            self.recorder.pause()
            if self._recording_started_at is not None:
                self._recorded_seconds += time.monotonic() - self._recording_started_at
            self._recording_started_at = None
            self._set_recording_controls("paused")
        elif self.recorder.state == "paused":
            self.recorder.resume()
            self._recording_started_at = time.monotonic()
            self._set_recording_controls("recording")
        self._update_recording_status()

    def _stop_recording(self) -> None:
        if self.recorder.state in {"recording", "paused"}:
            if self._recording_started_at is not None:
                self._recorded_seconds += time.monotonic() - self._recording_started_at
            self._recording_started_at = None
            self.recorder.stop()
            self.recording_timer.stop()
            self._set_recording_controls("stopped")
            self.recording_page_status.setText(
                f"錄音停止，共 {self._recorded_seconds:.1f} 秒。按「存檔」保存 WAV。"
            )
            self._update_recording_status()

    def _set_recording_controls(self, state: str) -> None:
        self.record_button.setEnabled(state in {"idle", "stopped"})
        self.pause_record_button.setEnabled(state in {"recording", "paused"})
        self.stop_record_button.setEnabled(state in {"recording", "paused"})
        self.save_record_button.setEnabled(state == "stopped")
        self.pause_record_button.setText(
            "▶ 繼續" if state == "paused" else "Ⅱ 暫停"
        )

    def _update_recording_status(self) -> None:
        elapsed = self._recorded_seconds
        if self._recording_started_at is not None:
            elapsed += time.monotonic() - self._recording_started_at
        minutes, seconds = divmod(int(elapsed), 60)
        if self.recorder.state == "recording":
            text = f"● 錄音中 {minutes:02d}:{seconds:02d}"
            color = "#ff706f"
        elif self.recorder.state == "paused":
            text = f"Ⅱ 錄音已暫停 {minutes:02d}:{seconds:02d}"
            color = "#e9c46a"
        else:
            text = "● 未錄音"
            color = "#92aaa9"
        self.recording_status.setText(text)
        self.recording_status.setStyleSheet(f"color: {color}; font-size: 10px;")

    def _save_recording(self) -> None:
        if self.recorder.state in {"recording", "paused"}:
            self._stop_recording()
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        default_name = self.recordings_dir / (
            f"SPL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        )
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "儲存錄音", str(default_name), "WAV 音訊 (*.wav)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".wav"):
            file_path += ".wav"
        try:
            saved_path = self.recorder.save(file_path)
            self.recording_page_status.setText(f"已儲存：{saved_path.name}")
            self._refresh_recordings()
        except (OSError, ValueError) as error:
            self.recording_page_status.setText(f"存檔失敗：{error}")

    def _refresh_recordings(self) -> None:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.recording_files.clear()
        for file_path in sorted(
            self.recordings_dir.glob("*.wav"), key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            item = QtWidgets.QListWidgetItem(file_path.name)
            item.setData(QtCore.Qt.UserRole, str(file_path))
            item.setText(f"{file_path.name}  ·  {file_path.stat().st_size / 1024:.0f} KiB")
            self.recording_files.addItem(item)

    def _play_selected_recording(self, item=None) -> None:
        if item is None:
            item = self.recording_files.currentItem()
        if item is None:
            self.recording_page_status.setText("請先選取一個 WAV 錄音檔。")
            return
        if self.recorder.state in {"recording", "paused"}:
            self.recording_page_status.setText("請先停止目前錄音，再播放音檔。")
            return
        try:
            sample_rate, samples = AudioRecorder.load(item.data(QtCore.Qt.UserRole))
            sd.play(samples, sample_rate, blocking=False)
            self.recording_page_status.setText(f"正在播放：{item.text().split('  ·')[0]}")
        except (OSError, sd.PortAudioError, ValueError) as error:
            self.recording_page_status.setText(f"播放失敗：{error}")

    @staticmethod
    def _stop_playback() -> None:
        try:
            sd.stop()
        except sd.PortAudioError:
            pass

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_recordings()

    def _update_calibration_status(self) -> None:
        factor = self.dsp.cal_factor
        uncalibrated_factor = float(
            self.config.get("uncalibrated_cal_factor", 1.0)
        )
        if np.isclose(factor, uncalibrated_factor):
            self.calibration_status.setText("● 未校正 · 數值僅供估算")
            self.calibration_status.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #e9c46a;"
            )
        else:
            self.calibration_status.setText(f"● 已校正 · cal_factor = {factor:.6g} Pa/unit")
            self.calibration_status.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #74ddbb;"
            )

    def _start_calibration(self) -> None:
        if not self.audio_active:
            self.calibration_status.setText("無可用麥克風，無法校正。")
            return
        if self.recorder.state in {"recording", "paused"}:
            self.calibration_status.setText("請先停止錄音，再進行校正。")
            return
        self._calibration_reference_db = self.calibration_reference_spin.value()
        with self._audio_lock:
            self._calibration_chunks = []
            self._calibration_active = True
        self._calibration_started_at = time.monotonic()
        self.calibration_progress.setValue(0)
        self.start_calibration_button.setEnabled(False)
        self.calibration_status.setText("正在收集穩定的 1 kHz 校正音，請保持聲源不動…")
        self.calibration_timer.start()

    def _update_calibration_progress(self) -> None:
        if self._calibration_started_at is None:
            self.calibration_timer.stop()
            return
        elapsed = time.monotonic() - self._calibration_started_at
        self.calibration_progress.setValue(min(100, int(elapsed / 3.0 * 100)))
        if elapsed >= 3.0:
            self.calibration_timer.stop()
            self._finish_calibration()

    def _finish_calibration(self) -> None:
        with self._audio_lock:
            self._calibration_active = False
            chunks = self._calibration_chunks
            self._calibration_chunks = []
        self._calibration_started_at = None
        self.start_calibration_button.setEnabled(True)
        if not chunks:
            self.calibration_status.setText("沒有收集到音訊，請檢查麥克風後重試。")
            return
        samples = np.concatenate(chunks).astype(np.float64)
        if samples.size < self.sample_rate:
            self.calibration_status.setText("有效音訊不足 1 秒，請使用穩定聲源後重試。")
            return
        try:
            calibration_freqs, calibration_psd = self.dsp.compute_fft(samples)
            audible_bins = (calibration_freqs >= 20.0) & (
                calibration_freqs <= min(20000.0, self.sample_rate / 2)
            )
            if not np.any(audible_bins):
                raise ValueError("目前取樣率無法分析校正音")
            audible_indices = np.flatnonzero(audible_bins)
            dominant_index = audible_indices[
                np.argmax(calibration_psd[audible_indices])
            ]
            tone_peak = float(calibration_freqs[dominant_index])
            if abs(tone_peak - 1000.0) > 100.0:
                raise ValueError(
                    f"偵測到主頻 {tone_peak:.1f} Hz，請使用 1 kHz 校正音"
                )
            weighted = self.dsp.apply_a_weighting(samples)
            samples_per_window = max(1, self.sample_rate // 4)
            window_levels = []
            for start in range(0, weighted.size - samples_per_window + 1, samples_per_window):
                window_rms = self.dsp.compute_rms(
                    weighted[start:start + samples_per_window]
                )
                if window_rms > np.finfo(np.float64).tiny:
                    window_levels.append(20.0 * np.log10(window_rms))
            if len(window_levels) < 4 or np.std(window_levels) > 1.5:
                raise ValueError("校正音量不夠穩定，請固定聲源與麥克風後重試")
            digital_rms = self.dsp.compute_rms(weighted)
            if digital_rms <= np.finfo(np.float64).tiny:
                raise ValueError("訊號太小，無法計算校正係數")
            known_pressure = self.dsp.p_ref * 10.0 ** (
                self._calibration_reference_db / 20.0
            )
            new_factor = known_pressure / digital_rms
            updated_config = dict(self.config)
            updated_config["cal_factor"] = new_factor
            updated_config["calibration_reference_db"] = self._calibration_reference_db
            temporary_path = self.config_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(updated_config, indent=2) + "\n", encoding="utf-8"
            )
            temporary_path.replace(self.config_path)
            self.config.update(updated_config)
            self.dsp.cal_factor = new_factor
            self.calibration_progress.setValue(100)
            self._reset_measurements()
            self._update_calibration_status()
        except (OSError, ValueError, FloatingPointError) as error:
            self.calibration_status.setText(f"校正失敗：{error}")

    def _reset_calibration(self) -> None:
        self.calibration_timer.stop()
        with self._audio_lock:
            self._calibration_active = False
            self._calibration_chunks = []
        self._calibration_started_at = None
        self.start_calibration_button.setEnabled(True)
        factory_factor = float(self.config.get("uncalibrated_cal_factor", 1.0))
        updated_config = dict(self.config)
        updated_config["cal_factor"] = factory_factor
        updated_config.pop("calibration_reference_db", None)
        try:
            temporary_path = self.config_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(updated_config, indent=2) + "\n", encoding="utf-8"
            )
            temporary_path.replace(self.config_path)
            self.config.update(updated_config)
            self.dsp.cal_factor = factory_factor
            self.calibration_progress.setValue(0)
            self._reset_measurements()
            self._update_calibration_status()
        except OSError as error:
            self.calibration_status.setText(f"重置失敗，設定檔無法寫入：{error}")

    def _update_dashboard(self) -> None:
        with self._audio_lock:
            samples = self._latest_audio.astype(np.float64, copy=True)
            audio_error = self._audio_error

        if not self._has_audio or samples.size == 0:
            if not self.audio_active and self._audio_error:
                self.status_label.setText("MICROPHONE UNAVAILABLE: check input device")
                self.status_label.setStyleSheet("color: #ff8c78;")
            return
        self._time_signal = samples
        self._time_axis = np.arange(samples.size, dtype=np.float64) / self.sample_rate
        try:
            weighted = self.dsp.process_weighted_signal(samples, self.weighting)
            pressure_samples = weighted * self.dsp.cal_factor
            block_power = float(np.mean(np.square(pressure_samples)))
            self._pressure_square_sum += float(np.sum(np.square(pressure_samples)))
            self._pressure_sample_count += pressure_samples.size
            if self.time_response == "IMPULSE":
                attack_seconds, release_seconds = 0.035, 1.5
            elif self.time_response == "FAST":
                attack_seconds = release_seconds = 0.125
            else:
                attack_seconds = release_seconds = 1.0
            if self._detector_power is None:
                self._detector_power = float(np.square(pressure_samples[0]))
            attack_smoothing = np.exp(-1.0 / (self.sample_rate * attack_seconds))
            release_smoothing = np.exp(-1.0 / (self.sample_rate * release_seconds))
            for sample_power in np.square(pressure_samples):
                smoothing = (
                    attack_smoothing
                    if sample_power > self._detector_power
                    else release_smoothing
                )
                self._detector_power = float(
                    smoothing * self._detector_power
                    + (1.0 - smoothing) * sample_power
                )
            safe_detector_power = max(
                self._detector_power, np.finfo(np.float64).tiny
            )
            self._current_spl = float(
                10.0 * np.log10(safe_detector_power / (self.dsp.p_ref ** 2))
            )
            self._max_spl = max(self._max_spl, self._current_spl)
        except (ValueError, FloatingPointError) as error:
            self.status_label.setText(f"DSP ERROR: {error}")
            return

        self.spl_value.setText(f"{self._current_spl:05.1f}")
        self.max_value.setText(f"{self._max_spl:.1f} dB")
        mean_square_pressure = self._pressure_square_sum / max(
            self._pressure_sample_count, 1
        )
        safe_mean_square = max(mean_square_pressure, np.finfo(np.float64).tiny)
        leq = 10.0 * np.log10(safe_mean_square / (self.dsp.p_ref ** 2))
        self.leq_value.setText(f"{leq:.1f} dB")

        self.time_curve.setData(self._time_axis, self._time_signal)
        freqs, psd_db = self.dsp.compute_fft(samples)
        valid_peak_band = (
            (freqs >= self._peak_min_hz)
            & (freqs <= self._peak_max_hz)
            & (freqs > 0)
        )
        if np.any(valid_peak_band):
            candidate_indices = np.flatnonzero(valid_peak_band)
            peak_index = candidate_indices[np.argmax(psd_db[candidate_indices])]
            self._peak_frequency = float(freqs[peak_index])
            self._peak_level = float(psd_db[peak_index])
            self.analysis_peak_label.setText(
                f"Peak: {self._peak_frequency:.1f} Hz | {self._peak_level:.1f} dB/Hz"
            )
            self.analysis_curve.setData(freqs[1:], psd_db[1:])
            self.analysis_peak_marker.setData(
                [self._peak_frequency], [self._peak_level]
            )
        else:
            self._peak_frequency = 0.0
            self._peak_level = float("-inf")
            self.analysis_peak_label.setText("Peak: 頻帶內沒有有效頻率點")
        if self.chart_mode == "FFT":
            self.spectrum_curve.setData(freqs[1:], psd_db[1:])
            self.spectrum_plot.setXRange(20, min(20000, self.sample_rate / 2), padding=0)
        else:
            centers, band_db = self.dsp.compute_third_octave(freqs, psd_db)
            width = centers * (2 ** (1 / 6) - 2 ** (-1 / 6))
            self.oct_bars.setOpts(x=centers, height=band_db, width=width)
            self.spectrum_plot.setXRange(0, 21000, padding=0)

        if self._audio_error:
            self.status_label.setText(f"AUDIO: {audio_error}")
            self.status_label.setStyleSheet("color: #ffca76;")
        elif self.audio_active:
            sample_rate_text = (
                "48 kHz" if self.sample_rate == 48000
                else f"{self.sample_rate / 1000:g} kHz"
            )
            uncalibrated = np.isclose(
                self.dsp.cal_factor,
                float(self.config.get("uncalibrated_cal_factor", 1.0)),
            )
            suffix = " | UNCALIBRATED" if uncalibrated else ""
            self.status_label.setText(f"LIVE | {sample_rate_text}{suffix}")
            self.status_label.setStyleSheet(
                "color: #e9c46a;" if uncalibrated else "color: #56d6a0;"
            )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.timer.stop()
        self.recording_timer.stop()
        self.calibration_timer.stop()
        if self.recorder.state in {"recording", "paused"}:
            self.recorder.stop()
        self._stop_playback()
        if self.audio_input is not None:
            self.audio_input.stop()
        super().closeEvent(event)
