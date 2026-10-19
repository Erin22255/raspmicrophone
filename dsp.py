"""Signal processing helpers for the SPL meter."""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal


class AudioDSP:
    """Convert microphone samples into SPL and frequency-domain measures.

    ``cal_factor`` converts one input-sample unit to pascals. It must be
    determined with a calibrated acoustic source for meaningful SPL readings.
    """

    _A_POLES = (-20.598997, -20.598997, -107.65265, -737.86223,
                -12194.217, -12194.217)
    _C_POLES = (-20.598997, -20.598997, -12194.217, -12194.217)
    _THIRD_OCTAVE_CENTERS = np.array(
        [20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315,
         400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
         5000, 6300, 8000, 10000, 12500, 16000, 20000],
        dtype=np.float64,
    )

    def __init__(self, sample_rate: int, p_ref: float, cal_factor: float):
        if sample_rate <= 2000:
            raise ValueError("sample_rate must be greater than 2000 Hz")
        if p_ref <= 0:
            raise ValueError("p_ref must be greater than zero")
        if cal_factor <= 0:
            raise ValueError("cal_factor must be greater than zero")

        self.sample_rate = int(sample_rate)
        self.p_ref = float(p_ref)
        self.cal_factor = float(cal_factor)
        self._a_b, self._a_a = self._design_weighting_filter("A")
        self._c_b, self._c_a = self._design_weighting_filter("C")

    def _design_weighting_filter(self, weighting: str) -> tuple[np.ndarray, np.ndarray]:
        """Bilinear-transform an IEC-style analog weighting prototype."""
        if weighting == "A":
            poles = self._A_POLES
            zeros = (0.0, 0.0, 0.0, 0.0)
        else:
            poles = self._C_POLES
            zeros = (0.0, 0.0)

        numerator = np.poly(zeros)
        denominator = np.poly(poles)
        numerator *= denominator[-1]
        b_coeff, a_coeff = scipy_signal.bilinear(
            numerator, denominator, fs=self.sample_rate
        )

        _, response = scipy_signal.freqz(
            b_coeff, a_coeff, worN=np.array([1000.0]), fs=self.sample_rate
        )
        gain = abs(response[0])
        if not np.isfinite(gain) or gain == 0:
            raise ValueError(f"Could not normalize the {weighting}-weighting filter")
        return b_coeff / gain, a_coeff

    @staticmethod
    def _as_signal(samples: np.ndarray) -> np.ndarray:
        data = np.asarray(samples, dtype=np.float64)
        if data.ndim != 1:
            raise ValueError("signal must be a one-dimensional mono array")
        if data.size == 0:
            raise ValueError("signal must not be empty")
        if not np.all(np.isfinite(data)):
            raise ValueError("signal must contain only finite samples")
        return data

    def _apply_filter(
        self, samples: np.ndarray, b_coeff: np.ndarray, a_coeff: np.ndarray
    ) -> np.ndarray:
        data = self._as_signal(samples)
        initial_state = scipy_signal.lfilter_zi(b_coeff, a_coeff) * data[0]
        filtered, _ = scipy_signal.lfilter(
            b_coeff, a_coeff, data, zi=initial_state
        )
        return filtered

    def apply_a_weighting(self, samples: np.ndarray) -> np.ndarray:
        """Apply A-weighting to a mono time-domain signal."""
        return self._apply_filter(samples, self._a_b, self._a_a)

    def apply_c_weighting(self, samples: np.ndarray) -> np.ndarray:
        """Apply C-weighting to a mono time-domain signal."""
        return self._apply_filter(samples, self._c_b, self._c_a)

    @staticmethod
    def compute_rms(samples: np.ndarray) -> float:
        """Return the root-mean-square amplitude of a mono signal."""
        data = AudioDSP._as_signal(samples)
        return float(np.sqrt(np.mean(np.square(data))))

    def calculate_spl(self, samples: np.ndarray, weighting: str = "A") -> float:
        """Return dB SPL using A, C, or Z (unweighted) frequency weighting."""
        mode = weighting.upper()
        if mode == "A":
            measured = self.apply_a_weighting(samples)
        elif mode == "C":
            measured = self.apply_c_weighting(samples)
        elif mode == "Z":
            measured = self._as_signal(samples)
        else:
            raise ValueError("weighting must be 'A', 'C', or 'Z'")

        pressure_rms = self.compute_rms(measured) * self.cal_factor
        safe_pressure = max(pressure_rms, np.finfo(np.float64).tiny)
        return float(20.0 * np.log10(safe_pressure / self.p_ref))

    def compute_fft(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return frequencies and a Hann-window, one-sided PSD in dB/Hz."""
        data = self._as_signal(samples)
        freqs, psd = scipy_signal.periodogram(
            data,
            fs=self.sample_rate,
            window="hann",
            detrend=False,
            return_onesided=True,
            scaling="density",
        )
        psd_db = 10.0 * np.log10(np.maximum(psd, np.finfo(np.float64).tiny))
        return freqs, psd_db

    @classmethod
    def compute_third_octave(
        cls, freqs: np.ndarray, psd_db: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Integrate PSD into standard nominal 1/3-octave bands from 20 Hz."""
        frequencies = np.asarray(freqs, dtype=np.float64)
        spectrum_db = np.asarray(psd_db, dtype=np.float64)
        if frequencies.ndim != 1 or spectrum_db.ndim != 1:
            raise ValueError("freqs and psd_db must be one-dimensional arrays")
        if frequencies.size != spectrum_db.size or frequencies.size < 2:
            raise ValueError("freqs and psd_db must have equal length of at least 2")
        if np.any(np.diff(frequencies) <= 0):
            raise ValueError("freqs must be strictly increasing")
        if not np.all(np.isfinite(frequencies)) or np.any(np.isnan(spectrum_db)):
            raise ValueError("freqs and psd_db must not contain NaN values")

        bin_width = float(np.median(np.diff(frequencies)))
        psd_linear = np.power(10.0, spectrum_db / 10.0)
        band_power = np.zeros(cls._THIRD_OCTAVE_CENTERS.size, dtype=np.float64)
        lower_ratio = 2.0 ** (-1.0 / 6.0)
        upper_ratio = 2.0 ** (1.0 / 6.0)

        for index, center in enumerate(cls._THIRD_OCTAVE_CENTERS):
            in_band = (frequencies >= center * lower_ratio) & (
                frequencies < center * upper_ratio
            )
            if np.any(in_band):
                band_power[index] = np.sum(psd_linear[in_band]) * bin_width

        band_db = 10.0 * np.log10(
            np.maximum(band_power, np.finfo(np.float64).tiny)
        )
        return cls._THIRD_OCTAVE_CENTERS.copy(), band_db