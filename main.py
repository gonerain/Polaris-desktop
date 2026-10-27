"""Desktop entry point: persistent calendar, single-instance lock and optional tray."""

from pathlib import Path
import sys

from PySide6.QtCore import QObject, QTimer, QUrl, QStandardPaths, QLockFile
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from polaris.qml import register_types
from polaris.input_focus import InputFocusFilter
from polaris.x11_hints import apply_skip_taskbar


QML_FILE = Path(__file__).resolve().parent / "qml" / "Main.qml"


def create_engine(*, storage_path=None) -> QQmlApplicationEngine:
    register_types()
    engine = QQmlApplicationEngine()
    engine._input_focus = InputFocusFilter(engine)
    QGuiApplication.instance().installEventFilter(engine._input_focus)
    engine.addImportPath(str(QML_FILE.parent))
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        raise RuntimeError(f"无法加载日程界面：{QML_FILE}")
    window = engine.rootObjects()[0]
    store = window.findChild(QObject, "calendarTaskStore")
    coordinator = window.findChild(QObject, "interactionCoordinator")
    if store is None or coordinator is None:
        raise RuntimeError("找不到日程组件或联动协调器")
    if storage_path is not None:
        store.initialize_storage(storage_path)
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
    from PySide6.QtWidgets import QApplication
    from polaris.desktop import create_tray

    app = QApplication(sys.argv)
    app.setApplicationName("Polaris")
    app.setOrganizationName("Polaris")
    data_directory = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    try:
        data_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _show_startup_error(f"无法创建日程数据目录：{error}")
        return 1
    lock = QLockFile(str(data_directory / "app.lock"))
    if not lock.tryLock(0):
        _show_startup_error("Polaris 已在运行，或数据目录无法锁定。请勿重复启动。")
        return 1
    engine = create_engine(storage_path=data_directory / "tasks.json")
    window = engine.rootObjects()[0]
    tray = create_tray(app, window, window.findChild(QObject, "interactionCoordinator"), data_directory)
    exit_code = app.exec()
    if tray is not None:
        tray.hide()
    del engine
    return exit_code


def _show_startup_error(message):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Polaris", 0x40)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
