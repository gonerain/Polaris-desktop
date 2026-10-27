"""Linux 悬浮写字板的 Python 入口，界面由 Qt Quick/QML 实现。"""

from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from polaris.qml import register_types


QML_FILE = Path(__file__).resolve().parent / "qml" / "Main.qml"


def create_engine() -> QQmlApplicationEngine:
    register_types()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_FILE.parent))
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        raise RuntimeError(f"无法加载写字板界面：{QML_FILE}")
    return engine


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Polaris")
    engine = create_engine()
    exit_code = app.exec()
    del engine
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
