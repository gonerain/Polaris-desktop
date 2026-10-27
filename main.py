"""Linux 悬浮日程的 Python 入口，界面由 Qt Quick/QML 实现。"""

from pathlib import Path
import sys

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from polaris.qml import register_types
from polaris.x11_hints import apply_skip_taskbar


QML_FILE = Path(__file__).resolve().parent / "qml" / "Main.qml"


def create_engine() -> QQmlApplicationEngine:
    register_types()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_FILE.parent))
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        raise RuntimeError(f"无法加载日程界面：{QML_FILE}")
    window = engine.rootObjects()[0]
    store = window.findChild(QObject, "calendarTaskStore")
    coordinator = window.findChild(QObject, "interactionCoordinator")
    if store is None or coordinator is None:
        raise RuntimeError("找不到日程组件或联动协调器")
    coordinator.attach(store)
    if QGuiApplication.instance() is not None:
        # 首次在窗口映射前设置；再延迟一次，确保窗口管理器已创建原生窗口。
        apply_skip_taskbar(window)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.setInterval(200)
        timer.timeout.connect(lambda: apply_skip_taskbar(window))
        timer.start()
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
