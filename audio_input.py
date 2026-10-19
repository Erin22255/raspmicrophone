"""Microphone discovery and mono audio capture using sounddevice."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import sounddevice as sd


AudioCallback = Callable[[np.ndarray, str], None]


class AudioInput:
    """Open the default or first available mono input at the requested rate."""

    def __init__(
        self,
        sample_rate: int,
        chunk_size: int,
        callback: AudioCallback,
        requested_device: int | str | None = None,
    ):
        self.sample_rate = int(sample_rate)
        self.chunk_size = int(chunk_size)
        self.callback = callback
        self.requested_device = requested_device
        self.stream: sd.InputStream | None = None
        self.device_name = ""
        self.error = ""

    @staticmethod
    def list_devices() -> list[dict]:
        """Return PortAudio device records for the run.py diagnostic command."""
        return list(sd.query_devices())

    def _candidate_devices(self, devices: list[dict]) -> list[int]:
        candidates: list[int] = []
        requested = self.requested_device
        if requested is not None:
            if isinstance(requested, int):
                candidates.append(requested)
            else:
                requested_name = requested.casefold()
                candidates.extend(
                    index for index, device in enumerate(devices)
                    if requested_name in device["name"].casefold()
                )

        try:
            default_input = sd.default.device[0]
            if default_input is not None and int(default_input) >= 0:
                candidates.append(int(default_input))
        except (TypeError, ValueError, IndexError):
            pass

        candidates.extend(
            index for index, device in enumerate(devices)
            if device["max_input_channels"] > 0
        )

        unique_candidates = list(dict.fromkeys(candidates))
        return [
            index for index in unique_candidates
            if 0 <= index < len(devices) and devices[index]["max_input_channels"] > 0
        ]

    def start(self) -> bool:
        """Try input devices until one starts; return whether capture is active."""
        try:
            devices = self.list_devices()
        except (sd.PortAudioError, OSError) as error:
            self.error = str(error)
            return False

        candidates = self._candidate_devices(devices)
        if not candidates:
            self.error = "No audio input devices are available"
            return False

        for device_index in candidates:
            stream = None
            try:
                stream = sd.InputStream(
                    device=device_index,
                    samplerate=self.sample_rate,
                    blocksize=self.chunk_size,
                    channels=1,
                    dtype="float32",
                    callback=self._sounddevice_callback,
                )
                stream.start()
                self.stream = stream
                self.device_name = str(devices[device_index]["name"])
                self.error = ""
                return True
            except (sd.PortAudioError, OSError, ValueError) as error:
                self.error = str(error)
                if stream is not None:
                    try:
                        stream.close()
                    except (sd.PortAudioError, OSError):
                        pass

        return False

    def _sounddevice_callback(self, indata, frames, time_info, status) -> None:
        del frames, time_info
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        self.callback(mono, str(status) if status else "")

    def stop(self) -> None:
        """Stop and release the active PortAudio stream, if any."""
        if self.stream is None:
            return
        try:
            if self.stream.active:
                self.stream.stop()
        finally:
            self.stream.close()
            self.stream = None
