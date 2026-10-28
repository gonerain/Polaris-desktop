"""与 Qt 无关的 panel 分配、形状和像素区域计算。"""

from dataclasses import dataclass, replace
from math import isfinite, isqrt
from numbers import Real


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass(frozen=True)
class Allocation:
    id: int
    origin: tuple[int, int]
    cells: tuple[tuple[int, int], ...]
    x: float
    y: float
    width: float
    height: float
    regions: tuple[Rect, ...]

    def as_dict(self) -> dict:
        return {
            "ok": True,
            "id": self.id,
            "origin": list(self.origin),
            "cells": [list(cell) for cell in self.cells],
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "regions": [rect.as_dict() for rect in self.regions],
        }


def _dimension(value, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} 必须是有限数值")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} 必须{'非负' if allow_zero else '大于零'}")
    return float(value)


def normalize_cells(cells) -> tuple[tuple[int, int], ...]:
    if not isinstance(cells, (list, tuple)) or not cells:
        raise ValueError("cells 必须是非空坐标集合")
    result = set()
    for cell in cells:
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            raise ValueError("每个格子必须是 [列, 行]")
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in cell):
            raise ValueError("格子坐标必须是非负整数")
        coordinate = tuple(cell)
        if coordinate in result:
            raise ValueError("格子坐标不能重复")
        result.add(coordinate)
    left, top = min(x for x, _ in result), min(y for _, y in result)
    return tuple(sorted(((x - left, y - top) for x, y in result), key=lambda p: (p[1], p[0])))


def shape_regions(cells, width: float, height: float, gap: float) -> tuple[Rect, ...]:
    """生成互不重叠的矩形覆盖；相邻同属格子之间的间距合并，孔洞仍留白。"""
    occupied = set(cells)
    columns = max(x for x, _ in cells) + 1
    rows = max(y for _, y in cells) + 1
    xs = [0.0]
    ys = [0.0]
    for index in range(columns * 2 - 1):
        xs.append(xs[-1] + (width if index % 2 == 0 else gap))
    for index in range(rows * 2 - 1):
        ys.append(ys[-1] + (height if index % 2 == 0 else gap))

    active = {}
    rectangles = []
    for row in range(len(ys) - 1):
        if ys[row + 1] == ys[row]:
            continue
        runs = []
        start = None
        for column in range(len(xs) - 1):
            neighbors_x = (column // 2,) if column % 2 == 0 else (column // 2, column // 2 + 1)
            neighbors_y = (row // 2,) if row % 2 == 0 else (row // 2, row // 2 + 1)
            filled = all((x, y) in occupied for x in neighbors_x for y in neighbors_y)
            if filled and start is None:
                start = xs[column]
            if start is not None and (not filled or column == len(xs) - 2):
                end = xs[column] if not filled else xs[column + 1]
                if end > start:
                    runs.append((start, end))
                start = None
        following = {}
        for left, right in runs:
            key = (left, right)
            previous = active.pop(key, None)
            if previous is not None:
                following[key] = Rect(left, previous.y, right - left, ys[row + 1] - previous.y)
            else:
                following[key] = Rect(left, ys[row], right - left, ys[row + 1] - ys[row])
        rectangles.extend(active.values())
        active = following
    rectangles.extend(active.values())
    return tuple(rectangles)


class PanelAllocator:
    def __init__(self, panel_size=(120, 80), panel_count: int = 12, gap: float = 8):
        self._allocations = {}
        self._occupied = {}
        self._next_id = 1
        self.configure(panel_size, panel_count, gap)

    def configure(self, panel_size, panel_count: int, gap: float) -> None:
        if not isinstance(panel_size, (list, tuple)) or len(panel_size) != 2:
            raise ValueError("panelSize 必须包含宽和高")
        width = _dimension(panel_size[0], "panel 宽度")
        height = _dimension(panel_size[1], "panel 高度")
        gap = _dimension(gap, "gap", allow_zero=True)
        if isinstance(panel_count, bool) or not isinstance(panel_count, int) or panel_count < 1:
            raise ValueError("panelCount 必须是正整数")
        if self._allocations:
            raise ValueError("请先释放全部组件，再修改画板初始化参数")
        columns = isqrt(panel_count - 1) + 1
        rows = (panel_count + columns - 1) // columns
        try:
            board_width = columns * width + (columns - 1) * gap
            board_height = rows * height + (rows - 1) * gap
        except OverflowError as error:
            raise ValueError("画板尺寸溢出") from error
        if not isfinite(board_width) or not isfinite(board_height):
            raise ValueError("画板尺寸溢出")
        self.panel_size = (width, height)
        self.panel_count = panel_count
        self.gap = gap
        self.columns, self.rows = columns, rows
        self.width, self.height = board_width, board_height

    @property
    def free_count(self) -> int:
        return self.panel_count - len(self._occupied)

    def request(self, cells=((0, 0),)) -> Allocation | None:
        shape = normalize_cells(cells)
        span_x = max(x for x, _ in shape) + 1
        span_y = max(y for _, y in shape) + 1
        width, height = self.panel_size
        for row in range(self.rows - span_y + 1):
            for column in range(self.columns - span_x + 1):
                absolute = [(column + x, row + y) for x, y in shape]
                if any(y * self.columns + x >= self.panel_count or (x, y) in self._occupied for x, y in absolute):
                    continue
                allocation = Allocation(
                    self._next_id, (column, row), shape,
                    column * (width + self.gap), row * (height + self.gap),
                    span_x * width + (span_x - 1) * self.gap,
                    span_y * height + (span_y - 1) * self.gap,
                    shape_regions(shape, width, height, self.gap),
                )
                self._next_id += 1
                self._allocations[allocation.id] = allocation
                self._occupied.update({cell: allocation.id for cell in absolute})
                return allocation
        return None

    def move(self, allocation_id: int, column: int, row: int, *, swap=True):
        """Atomically exchange a cardinal group, preserving perpendicular origins."""
        if type(swap) is not bool:
            raise ValueError("swap 必须是布尔值")
        if any(type(value) is not int or value < 0 for value in (allocation_id, column, row)):
            raise ValueError("分配 ID 和目标 cell 必须是非负整数")
        source = self._allocations.get(allocation_id)
        if source is None:
            return None

        def cells_at(allocation, origin):
            cells = {(origin[0] + x, origin[1] + y) for x, y in allocation.cells}
            if any(x >= self.columns or y >= self.rows or y * self.columns + x >= self.panel_count
                   for x, y in cells):
                return None
            return cells

        target = column, row
        dx, dy = column - source.origin[0], row - source.origin[1]
        if abs(dx) + abs(dy) > 1:
            return None  # Only adjacent cardinal moves; never diagonal/free placement.
        destination = cells_at(source, target)
        if destination is None:
            return None
        origins = {allocation_id: target}
        pending = [allocation_id]
        while pending:
            mover_id = pending.pop()
            mover = self._allocations[mover_id]
            cells = cells_at(mover, origins[mover_id])
            if cells is None:
                return None
            for cell in sorted(cells):
                other_id = self._occupied.get(cell)
                if other_id is None or other_id in origins:
                    continue
                if not swap:
                    return None
                other = self._allocations[other_id]
                # A wide row may exchange with several single-cell components.
                # Follow blockers along this axis only; validate the entire group
                # before touching the occupancy map or any allocation identity.
                origins[other_id] = ((mover.origin[0], other.origin[1]) if dx
                                     else (other.origin[0], mover.origin[1]))
                pending.append(other_id)
        occupied = {cell: owner for cell, owner in self._occupied.items() if owner not in origins}
        changed = []
        for identity, origin in origins.items():
            allocation = self._allocations[identity]
            cells = cells_at(allocation, origin)
            if cells is None or any(cell in occupied for cell in cells):
                return None
            occupied.update({cell: identity for cell in cells})
            changed.append(replace(allocation, origin=origin,
                                   x=origin[0] * (self.panel_size[0] + self.gap),
                                   y=origin[1] * (self.panel_size[1] + self.gap)))
        self._occupied = occupied
        self._allocations.update({allocation.id: allocation for allocation in changed})
        return tuple(changed)

    def release(self, allocation_id: int) -> bool:
        if isinstance(allocation_id, bool) or not isinstance(allocation_id, int):
            return False
        allocation = self._allocations.pop(allocation_id, None)
        if allocation is None:
            return False
        for x, y in allocation.cells:
            del self._occupied[(allocation.origin[0] + x, allocation.origin[1] + y)]
        return True
