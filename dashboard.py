"""Live 800x480 SPL meter dashboard for a laptop or Raspberry Pi."""

from __future__ import annotations

import threading

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from dsp import AudioDSP


class SPLDashboard(QtWidgets.QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.sample_rate = int(config["sample_rate"])
        self.chunk_size = int(config["chunk_size"])
        self.dsp = AudioDSP(
            self.sample_rate, float(config["p_ref"]), float(config["cal_factor"])
        )
        self.weighting = config["weighting"]
        self.chart_mode = "FFT"
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
        self.spl_unit = QtWidgets.QLabel("dB SPL A")
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
            button.clicked.connect(lambda checked, value=mode: self._set_weighting(value))
            weighting_group.addButton(button)
            weighting_row.addWidget(button)
            self.weight_buttons[mode] = button
        left.addLayout(weighting_row)

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
        self.setCentralWidget(central)

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
        self._reset_measurements()

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
        self.leq_value.setText("--.- dB")
        self.max_value.setText("--.- dB")

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
            self._current_spl = self.dsp.calculate_spl(samples, self.weighting)
            if self.weighting == "A":
                weighted = self.dsp.apply_a_weighting(samples)
            elif self.weighting == "C":
                weighted = self.dsp.apply_c_weighting(samples)
            else:
                weighted = samples
            pressure_samples = weighted * self.dsp.cal_factor
            self._pressure_square_sum += float(np.sum(np.square(pressure_samples)))
            self._pressure_sample_count += pressure_samples.size
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
            self.status_label.setText("LIVE  |  48 kHz" if self.sample_rate == 48000
                                      else f"LIVE  |  {self.sample_rate / 1000:g} kHz")
            self.status_label.setStyleSheet("color: #56d6a0;")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.timer.stop()
        if self.audio_input is not None:
            self.audio_input.stop()
        super().closeEvent(event)
