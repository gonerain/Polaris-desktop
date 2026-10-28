import QtQuick
import Polaris 1.0

Item {
    id: board

    property alias panelSize: allocator.panelSize
    property alias panelCount: allocator.panelCount
    property alias gap: allocator.gap
    // Bindings may run while Python-owned objects are being torn down.
    readonly property int columns: allocator ? allocator.columns : 1
    readonly property int rows: allocator ? allocator.rows : 1
    readonly property int freePanelCount: allocator ? allocator.freeCount : 0
    readonly property string lastError: allocator ? allocator.lastError : ""
    // 画板获得实际尺寸时，格子随之伸展；独立使用自然尺寸时等于 panelSize。
    readonly property real cellWidth: Math.max(1, (width - (columns - 1) * gap) / columns)
    readonly property real cellHeight: Math.max(1, (height - (rows - 1) * gap) / rows)
    property var _handles: ({})
    // The presenter belongs to the window, not the allocator.
    property var presenter: null
    property bool interactionsEnabled: true
    property bool dragging: false
    property Item activeDragHost: null
    property Item movingHost: null
    readonly property bool settling: settleTimer.running
    readonly property bool layoutLocked: !interactionsEnabled || (presenter && presenter.busy)
    readonly property int chromeHeight: 32
    readonly property int moveDuration: 110

    Timer {
        id: settleTimer
        interval: board.moveDuration + 25
        onTriggered: {
            board.movingHost = null
            const host = board.activeDragHost
            // Run after the one-shot timer has fully stopped, not inside its
            // triggered signal while `running` can still be true.
            Qt.callLater(function() {
                if (host && board.activeDragHost === host && host.dragging)
                    host.updateMove(host.pointerPoint, false)
            })
        }
    }

    function present(handle, factory, options, properties): bool {
        if (dragging || settling || !presenter || !handle || _handles[String(handle.id)] !== handle)
            return false
        const resolved = Object.assign({}, options || {})
        if (resolved.span !== undefined) {
            const span = resolved.span
            if (!Number.isInteger(span.width) || !Number.isInteger(span.height)
                    || span.width < 1 || span.height < 1)
                return false
            resolved.size = Qt.size(span.width * panelSize.width + (span.width - 1) * gap,
                                    span.height * panelSize.height + (span.height - 1) * gap)
        }
        return presenter.open(handle, factory, resolved, properties)
    }

    function presentItem(item, factory, options, properties): bool {
        for (const key in _handles) {
            const handle = _handles[key]
            if (handle.item === item)
                return present(handle, factory, options, properties)
        }
        return false
    }

    implicitWidth: allocator ? allocator.boardWidth : 0
    implicitHeight: allocator ? allocator.boardHeight : 0
    clip: true

    PanelLayout { id: allocator }

    Component {
        id: hostFactory
        ComponentHost { }
    }

    function request(factory: Component, options: var, properties: var): var {
        if (!factory || factory.status !== Component.Ready)
            return {ok: false, error: "组件必须是已就绪的 QML Component"}
        const cells = options && options.cells !== undefined ? options.cells : [[0, 0]]
        const allocation = allocator.reserve(cells)
        if (!allocation.ok)
            return allocation
        let host = null
        try {
            host = hostFactory.createObject(board, {allocation: allocation, board: board,
                                                   caption: options && options.title ? options.title : "组件"}) as ComponentHost
            if (!host || !host.instantiate(factory, properties))
                throw new Error("组件创建失败，根对象必须是 Item")
            const handle = {ok: true, id: allocation.id, item: host.componentItem, allocation: allocation, host: host}
            _handles[String(handle.id)] = handle
            return handle
        } catch (error) {
            if (host) {
                host.visible = false
                host.destroy()
            }
            allocator.release(allocation.id)
            return {ok: false, error: String(error)}
        }
    }

    function move(handle, column, row, finalStep): bool {
        if (!handle || layoutLocked || (settling && !(finalStep && activeDragHost === handle.host))
                || _handles[String(handle.id)] !== handle || (dragging && activeDragHost !== handle.host)
                || !Number.isInteger(column) || !Number.isInteger(row) || column < 0 || row < 0)
            return false
        if (column === handle.allocation.origin[0] && row === handle.allocation.origin[1]) return true
        const result = allocator.relocate(handle.id, column, row, true)
        if (!result.ok) return false
        movingHost = handle.host
        settleTimer.restart()
        for (const allocation of result.allocations) {
            const moved = _handles[String(allocation.id)]
            moved.allocation = allocation
            moved.host.allocation = allocation
        }
        return true
    }

    function setMinimized(handle, minimized): bool {
        if (layoutLocked || dragging || settling || typeof minimized !== "boolean"
                || !handle || _handles[String(handle.id)] !== handle)
            return false
        handle.host.forceActiveFocus()
        handle.host.minimized = !!minimized
        return true
    }

    function handleFor(host) {
        return _handles[String(host.allocation.id)]
    }

    function hoverStep(host, point, finalStep): bool {
        if (point.x < 0 || point.y < 0 || point.x >= width || point.y >= height)
            return false
        const horizontal = host.moveAxis === "x"
        const pitch = horizontal ? cellWidth + gap : cellHeight + gap
        const distance = horizontal ? point.x - host.pressPoint.x : point.y - host.pressPoint.y
        const threshold = Math.min(48, pitch / 4)
        const steps = Math.abs(distance) < threshold ? 0
            : Math.sign(distance) * (1 + Math.floor((Math.abs(distance) - threshold) / pitch))
        const origin = host.allocation.origin
        const start = horizontal ? host.pressColumn : host.pressRow
        const current = (horizontal ? origin[0] : origin[1]) - start
        // Reverse at half the forward threshold, not at the same boundary.
        if (current > 0 && steps < current && distance > (current - 1) * pitch + threshold / 2)
            return false
        if (current < 0 && steps > current && distance < (current + 1) * pitch - threshold / 2)
            return false
        const direction = Math.sign(start + steps - (horizontal ? origin[0] : origin[1]))
        const column = horizontal ? origin[0] + direction : origin[0]
        const row = horizontal ? origin[1] : origin[1] + direction
        if (column === origin[0] && row === origin[1]) return false
        return move(handleFor(host), column, row, finalStep)
    }

    function containsComponentAt(point): bool {
        for (const key in _handles) {
            const host = _handles[key].host
            if (host.visible && host.containsPoint(host.mapFromItem(board, point.x, point.y)))
                return true
        }
        return false
    }

    function regionsFor(cells, cellWidth, cellHeight, gap): var {
        return allocator ? allocator.regionsFor(cells, cellWidth, cellHeight, gap) : []
    }

    function release(handle: var): bool {
        if (!handle || _handles[String(handle.id)] !== handle)
            return false
        if (settling || handle.host.dragging || (presenter && presenter.busy && presenter.sourceHandle === handle))
            return false
        delete _handles[String(handle.id)]
        if (handle.fullView) handle.fullView.destroy()
        handle.host.visible = false
        handle.host.destroy()
        allocator.release(handle.id)
        return true
    }
}
