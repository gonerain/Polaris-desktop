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

    function present(handle, factory, options, properties): bool {
        if (!presenter || !handle || _handles[String(handle.id)] !== handle)
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
            host = hostFactory.createObject(board, {allocation: allocation, board: board}) as ComponentHost
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

    function regionsFor(cells, cellWidth, cellHeight, gap): var {
        return allocator ? allocator.regionsFor(cells, cellWidth, cellHeight, gap) : []
    }

    function release(handle: var): bool {
        if (!handle || _handles[String(handle.id)] !== handle)
            return false
        if (presenter && presenter.busy && presenter.sourceHandle === handle)
            return false
        delete _handles[String(handle.id)]
        handle.host.visible = false
        handle.host.destroy()
        allocator.release(handle.id)
        return true
    }
}
