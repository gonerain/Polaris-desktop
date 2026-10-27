"""注册 QML 使用的 Python 类型；不创建窗口。"""

from PySide6.QtQml import qmlRegisterType, qmlRegisterUncreatableType

from .interactions import InteractionCoordinator
from .qt_board import PanelLayout, RegionSurface
from .tasks import CalendarTaskStore, TaskEntry

_registered = False


def register_types() -> None:
    global _registered
    if _registered:
        return
    qmlRegisterType(PanelLayout, "Polaris", 1, 0, "PanelLayout")
    qmlRegisterType(RegionSurface, "Polaris", 1, 0, "RegionSurface")
    qmlRegisterType(CalendarTaskStore, "Polaris", 1, 0, "CalendarTaskStore")
    qmlRegisterType(InteractionCoordinator, "Polaris", 1, 0, "InteractionCoordinator")
    qmlRegisterUncreatableType(TaskEntry, "Polaris", 1, 0, "TaskEntry", "任务由日历组件创建")
    _registered = True
