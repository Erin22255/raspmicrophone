"""Thread-safe in-memory WAV recording helpers for the SPL Meter."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from scipy.io import wavfile


class AudioRecorder:
    """Collect mono float audio blocks and save them as 16-bit PCM WAV."""

    def __init__(self, sample_rate: int):
        self.sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        self._blocks: list[np.ndarray] = []
        self._state = "idle"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self) -> None:
        with self._lock:
            self._blocks = []
            self._state = "recording"

    def pause(self) -> None:
        with self._lock:
            if self._state == "recording":
                self._state = "paused"

    def resume(self) -> None:
        with self._lock:
            if self._state == "paused":
                self._state = "recording"

    def add_audio(self, samples: np.ndarray) -> None:
        data = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
        if data.size == 0:
            return
        with self._lock:
            if self._state == "recording":
                self._blocks.append(data)

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._state in {"recording", "paused"}:
                self._state = "stopped"
            if not self._blocks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(self._blocks)

    def save(self, file_path: str | Path) -> Path:
        samples = self.stop()
        if samples.size == 0:
            raise ValueError("There is no recorded audio to save")

        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        wavfile.write(output_path, self.sample_rate, pcm)
        return output_path

    @staticmethod
    def load(file_path: str | Path) -> tuple[int, np.ndarray]:
        sample_rate, samples = wavfile.read(file_path)
        if samples.ndim == 2:
            samples = samples.astype(np.float64).mean(axis=1)

        if np.issubdtype(samples.dtype, np.integer):
            dtype_info = np.iinfo(samples.dtype)
            if np.issubdtype(samples.dtype, np.unsignedinteger):
                midpoint = (dtype_info.max + 1) / 2.0
                normalized = (
                    samples.astype(np.float32) - midpoint
                ) / midpoint
            else:
                scale = float(max(abs(dtype_info.min), dtype_info.max))
                normalized = samples.astype(np.float32) / scale
        else:
            normalized = samples.astype(np.float32)
        return int(sample_rate), normalized