from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from controllers.main_controller import MainController


def resource_path(relative_path: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("MMY-Tools")
    app.setApplicationName("MMY Action File Sync")
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.ico"))))

    controller = MainController()
    controller.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
