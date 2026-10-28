"""画板的 Qt 接口，以及不规则组件的输入边界。"""

import weakref
from math import isfinite

from PySide6.QtCore import Property, QEvent, QPointF, QRectF, QSizeF, Signal, Slot, QObject
from PySide6.QtGui import QEventPoint, QHoverEvent, QMouseEvent, QTouchEvent, QWheelEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QJSValue
from shiboken6 import isValid

from .panels import PanelAllocator, Rect, normalize_cells, shape_regions


class PanelLayout(QObject):
    configurationChanged = Signal()
    usageChanged = Signal()
    errorChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allocator = PanelAllocator()
        self._error = ""

    def _set_error(self, message):
        if message != self._error:
            self._error = message
            self.errorChanged.emit()

    @Slot(QSizeF, int, float, result=bool)
    def configure(self, size, count, gap):
        parameters = ((size.width(), size.height()), count, gap)
        if parameters == (self._allocator.panel_size, self._allocator.panel_count, self._allocator.gap):
            return True
        try:
            self._allocator.configure(*parameters)
        except ValueError as error:
            self._set_error(str(error))
            return False
        self._set_error("")
        self.configurationChanged.emit()
        self.usageChanged.emit()
        return True

    panelSize = Property(
        QSizeF,
        lambda self: QSizeF(*self._allocator.panel_size),
        lambda self, value: self.configure(value, self.panelCount, self.gap),
        notify=configurationChanged,
    )
    panelCount = Property(
        int, lambda self: self._allocator.panel_count,
        lambda self, value: self.configure(self.panelSize, value, self.gap),
        notify=configurationChanged,
    )
    gap = Property(
        float, lambda self: self._allocator.gap,
        lambda self, value: self.configure(self.panelSize, self.panelCount, value),
        notify=configurationChanged,
    )
    columns = Property(int, lambda self: self._allocator.columns, notify=configurationChanged)
    rows = Property(int, lambda self: self._allocator.rows, notify=configurationChanged)
    boardWidth = Property(float, lambda self: self._allocator.width, notify=configurationChanged)
    boardHeight = Property(float, lambda self: self._allocator.height, notify=configurationChanged)
    freeCount = Property(int, lambda self: self._allocator.free_count, notify=usageChanged)
    lastError = Property(str, lambda self: self._error, notify=errorChanged)

    @Slot("QVariantList", float, float, float, result="QVariantList")
    def regionsFor(self, cells, cell_width, cell_height, gap):
        """按当前有效格子尺寸重算显示/输入区域。"""
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
            for value in (cell_width, cell_height, gap)
        ):
            return []
        if cell_width <= 0 or cell_height <= 0 or gap < 0:
            return []
        try:
            shape = normalize_cells(cells)
            return [rect.as_dict() for rect in shape_regions(shape, cell_width, cell_height, gap)]
        except (TypeError, ValueError, OverflowError):
            return []

    @Slot("QVariantList", result="QVariantMap")
    def reserve(self, cells):
        try:
            allocation = self._allocator.request(cells)
        except ValueError as error:
            self._set_error(str(error))
            return {"ok": False, "error": self._error}
        if allocation is None:
            self._set_error("没有能容纳该形状的空闲 panel")
            return {"ok": False, "error": self._error}
        self._set_error("")
        self.usageChanged.emit()
        return allocation.as_dict()

    @Slot(int, int, int, bool, result="QVariantMap")
    def relocate(self, allocation_id, column, row, swap=True):
        try:
            changed = self._allocator.move(allocation_id, column, row, swap=swap)
        except ValueError as error:
            self._set_error(str(error))
            return {"ok": False, "error": self._error}
        if changed is None:
            self._set_error("目标无法容纳同轴换位组，布局保持不变")
            return {"ok": False, "error": self._error}
        self._set_error("")
        self.usageChanged.emit()
        return {"ok": True, "allocations": [allocation.as_dict() for allocation in changed]}

    @Slot(int, result=bool)
    def release(self, allocation_id):
        if not self._allocator.release(allocation_id):
            return False
        self.usageChanged.emit()
        return True


class _RegionInputMask(QObject):
    """把原有命中形状与已申请区域相交；不接管组件内部的输入处理。"""

    def __init__(self, surface, item, original):
        super().__init__(item)
        self.item = weakref.ref(item)
        if isinstance(original, _RegionInputMask):
            self.surfaces = original.surfaces + [weakref.ref(surface)]
            self.original = original.original
        else:
            self.surfaces = [weakref.ref(surface)]
            self.original = original

    def includes(self, surface):
        return any(reference() is surface for reference in self.surfaces)

    @Slot(QPointF, result=bool)
    def contains(self, point):
        item = self.item()
        if item is None or not isValid(item):
            return False
        for reference in self.surfaces:
            surface = reference()
            if surface is not None and isValid(surface) and not surface.contains(item.mapToItem(surface, point)):
                return False
        original = self.original
        if original is None or not isValid(original):
            return QRectF(0, 0, item.width(), item.height()).contains(point)
        if isinstance(original, QQuickItem):
            return original.contains(original.mapFromItem(item, point))
        result = original.contains(point)
        return result.toBool() if isinstance(result, QJSValue) else bool(result)


class RegionSurface(QQuickItem):
    """过滤子树边界外的初始输入；已开始的鼠标拖动仍可正常收到释放事件。"""

    regionsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._regions = ()
        self._mouse_buttons = set()
        self._touch_ids = set()
        self._observed = weakref.WeakSet()
        self._input_masks = weakref.WeakKeyDictionary()
        self._watching = False
        self.setClip(True)
        self.setFiltersChildMouseEvents(True)
        self.childrenChanged.connect(self._watch_tree)

    def get_regions(self):
        return [rect.as_dict() for rect in self._regions]

    def set_regions(self, values):
        self._regions = tuple(Rect(value["x"], value["y"], value["width"], value["height"]) for value in values)
        self.regionsChanged.emit()
        self._watch_tree()

    @Slot()
    def _watch_tree(self):
        # WheelHandler 不经过 childMouseEventFilter，必须让接收项自身的
        # contains() 也包含区域约束。直接调用 C++ setter 保留已有 QML binding。
        if self._watching or len(self._regions) < 2:
            return
        self._watching = True
        try:
            pending = list(self.childItems())
            while pending:
                item = pending.pop()
                pending.extend(item.childItems())
                if item not in self._observed:
                    self._observed.add(item)
                    item.childrenChanged.connect(self._watch_tree)
                    item.containmentMaskChanged.connect(self._watch_tree)
                current = item.containmentMask()
                old = self._input_masks.get(item)
                if isinstance(current, _RegionInputMask) and current.includes(self):
                    self._input_masks[item] = current
                    if isinstance(old, _RegionInputMask) and old is not current and isValid(old):
                        old.deleteLater()
                    continue
                mask = _RegionInputMask(self, item, current)
                item.setContainmentMask(mask)
                actual = item.containmentMask()
                self._input_masks[item] = actual
                if actual is not mask:
                    mask.deleteLater()
                if isinstance(old, _RegionInputMask) and old is not actual and isValid(old):
                    old.deleteLater()
        finally:
            self._watching = False

    regions = Property("QVariantList", get_regions, set_regions, notify=regionsChanged)

    def contains(self, point):
        return any(rect.contains(point.x(), point.y()) for rect in self._regions)

    @Slot(QPointF, result=bool)
    def containsPoint(self, point):
        return self.contains(point)

    def childMouseEventFilter(self, item, event):
        allowed = True
        if isinstance(event, QMouseEvent):
            inside = self.contains(item.mapToItem(self, event.position()))
            button = event.button()
            kind = event.type()
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                if inside:
                    self._mouse_buttons.add(button)
                else:
                    self._mouse_buttons.discard(button)
                allowed = inside
            elif kind == QEvent.Type.MouseButtonRelease:
                allowed = inside or button in self._mouse_buttons
                self._mouse_buttons.discard(button)
            else:
                allowed = inside or any(event.buttons() & pressed for pressed in self._mouse_buttons)
        elif isinstance(event, (QWheelEvent, QHoverEvent)):
            allowed = event.type() == QEvent.Type.HoverLeave or self.contains(item.mapToItem(self, event.position()))
        elif isinstance(event, QTouchEvent):
            if event.type() == QEvent.Type.TouchCancel:
                self._touch_ids.clear()
                return False
            points = event.points()
            for point in points:
                inside = self.contains(item.mapToItem(self, point.position()))
                if point.state() == QEventPoint.State.Pressed:
                    allowed = allowed and inside
                else:
                    allowed = allowed and (inside or point.id() in self._touch_ids)
            for point in points:
                if allowed and point.state() == QEventPoint.State.Pressed:
                    self._touch_ids.add(point.id())
                elif point.state() == QEventPoint.State.Released:
                    self._touch_ids.discard(point.id())
        if not allowed:
            event.setAccepted(False)
        return not allowed
