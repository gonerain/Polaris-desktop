"""One rule: clicking outside the focused text box releases its focus."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtQuick import QQuickWindow


class InputFocusFilter(QObject):
    @staticmethod
    def text_input(window):
        item = window.activeFocusItem()
        if item is not None and (item.inherits("QQuickTextInput") or item.inherits("QQuickTextEdit")):
            return item
        return None

    def eventFilter(self, watched, event):
        if not isinstance(watched, QQuickWindow):
            return False
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin, QEvent.Type.WindowDeactivate):
            return False
        item = self.text_input(watched)
        if item is None:
            return False
        if kind != QEvent.Type.WindowDeactivate:
            point = event.points()[0].position() if kind == QEvent.Type.TouchBegin else event.position()
            if item.contains(item.mapFromScene(point)):
                return False
        watched.contentItem().forceActiveFocus(Qt.FocusReason.MouseFocusReason)
        # Do not consume the event: the newly clicked input/control handles it normally.
        return False
