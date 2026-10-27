import QtQuick
import Polaris 1.0

Item {
    id: board

    property alias panelSize: allocator.panelSize
    property alias panelCount: allocator.panelCount
    property alias gap: allocator.gap
    readonly property int columns: allocator.columns
    readonly property int rows: allocator.rows
    readonly property int freePanelCount: allocator.freeCount
    readonly property string lastError: allocator.lastError
    // 画板获得实际尺寸时，格子随之伸展；独立使用自然尺寸时等于 panelSize。
    readonly property real cellWidth: Math.max(1, (width - (columns - 1) * gap) / columns)
    readonly property real cellHeight: Math.max(1, (height - (rows - 1) * gap) / rows)
    property var _handles: ({})

    implicitWidth: allocator.boardWidth
    implicitHeight: allocator.boardHeight
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
        return allocator.regionsFor(cells, cellWidth, cellHeight, gap)
    }

    function release(handle: var): bool {
        if (!handle || _handles[String(handle.id)] !== handle)
            return false
        delete _handles[String(handle.id)]
        handle.host.visible = false
        handle.host.destroy()
        allocator.release(handle.id)
        return true
    }
}
