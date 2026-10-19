"""Open the SPL dashboard layout without microphone input or sample values."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt5 import QtWidgets

PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    config_path = PROJECT_DIR / "config.json"
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot load project configuration: {error}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(PROJECT_DIR))
    from dashboard import SPLDashboard

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    dashboard = SPLDashboard(config)
    dashboard.setWindowTitle("SPL Meter | Interface Preview")
    dashboard.status_label.setText("INTERFACE PREVIEW | NO AUDIO INPUT")
    dashboard.status_label.setStyleSheet("color: #e9c46a;")
    dashboard.timer.stop()
    dashboard.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
