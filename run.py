"""Application entry point for the SPL Meter / Sound Lab."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PyQt5 import QtWidgets

from audio_input import AudioInput
from dashboard import SPLDashboard


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    required = {"sample_rate", "chunk_size", "p_ref", "cal_factor", "weighting"}
    missing = required.difference(config)
    if missing:
        raise ValueError(f"Missing configuration values: {', '.join(sorted(missing))}")
    if int(config["sample_rate"]) <= 2000 or int(config["chunk_size"]) <= 0:
        raise ValueError("sample_rate must be above 2000 and chunk_size must be positive")
    if float(config["p_ref"]) <= 0 or float(config["cal_factor"]) <= 0:
        raise ValueError("p_ref and cal_factor must be greater than zero")
    config["weighting"] = str(config["weighting"]).upper()
    if config["weighting"] not in {"A", "C", "Z"}:
        raise ValueError("weighting must be A, C, or Z")
    return config


def print_input_devices() -> int:
    try:
        devices = AudioInput.list_devices()
    except Exception as error:
        print(f"Unable to query audio devices: {error}", file=sys.stderr)
        return 1

    found_input = False
    for index, device in enumerate(devices):
        channels = int(device["max_input_channels"])
        if channels > 0:
            found_input = True
            print(f"{index}: {device['name']} ({channels} input channels)")
    if not found_input:
        print("No audio input devices found.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SPL Meter dashboard")
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="list available audio input devices and exit",
    )
    args = parser.parse_args(argv)
    if args.list_devices:
        return print_input_devices()

    try:
        config = load_config()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Configuration error in {CONFIG_PATH}: {error}", file=sys.stderr)
        return 1

    app = QtWidgets.QApplication(sys.argv[:1] + (argv or []))
    app.setStyle("Fusion")
    dashboard = SPLDashboard(config)
    audio_input = AudioInput(
        sample_rate=config["sample_rate"],
        chunk_size=config["chunk_size"],
        callback=dashboard.receive_audio,
        requested_device=config.get("input_device"),
    )
    dashboard.attach_audio_input(audio_input)
    dashboard.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())