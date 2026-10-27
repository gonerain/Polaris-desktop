pragma ComponentBehavior: Bound

import QtQuick
import Polaris 1.0

RegionSurface {
    id: host

    required property var allocation
    required property var board
    property Item componentItem: null
    readonly property bool rectangular: regions.length === 1
    readonly property bool softwareRendering: GraphicsInfo.api === GraphicsInfo.Software
    readonly property int spanX: {
        let maximum = 0
        for (let index = 0; index < allocation.cells.length; ++index)
            maximum = Math.max(maximum, allocation.cells[index][0])
        return maximum + 1
    }
    readonly property int spanY: {
        let maximum = 0
        for (let index = 0; index < allocation.cells.length; ++index)
            maximum = Math.max(maximum, allocation.cells[index][1])
        return maximum + 1
    }
    x: allocation.origin[0] * (board.cellWidth + board.gap)
    y: allocation.origin[1] * (board.cellHeight + board.gap)
    width: spanX * board.cellWidth + (spanX - 1) * board.gap
    height: spanY * board.cellHeight + (spanY - 1) * board.gap
    regions: board.regionsFor(allocation.cells, board.cellWidth, board.cellHeight, board.gap)
    visible: false

    function instantiate(factory: Component, properties: var): bool {
        const initial = Object.assign({}, properties || {}, {x: 0, y: 0, width: host.width, height: host.height})
        const object = factory.createObject(source, initial)
        const created = object as Item
        if (!created) {
            if (object)
                object.destroy()
            return false
        }
        componentItem = created
        created.width = Qt.binding(function() { return host.width })
        created.height = Qt.binding(function() { return host.height })
        visible = true
        return true
    }

    Item {
        id: source
        anchors.fill: parent
        readonly property var panelContext: ({
            width: host.width,
            height: host.height,
            cells: host.allocation.cells,
            regions: host.regions
        })
    }

    // 矩形直接渲染；不规则形状从同一实例中裁出互不重叠的片段。
    // ShaderEffectSource 是纹理源，不是 ShaderEffect；软件后端也可使用。
    Repeater {
        model: host.rectangular ? [] : host.regions

        Item {
            required property var modelData
            x: modelData.x
            y: modelData.y
            width: modelData.width
            height: modelData.height
            clip: true

            // 软件后端的高 DPI 反向投影会偏移：从零点正向捕获完整内容，
            // 在显示节点恢复纵向方向，再通过矩形视口裁剪。
            ShaderEffectSource {
                x: -parent.x
                y: -parent.y
                width: host.width
                height: host.height
                sourceItem: source
                sourceRect: Qt.rect(0, 0, host.width, host.height)
                textureMirroring: host.softwareRendering ? ShaderEffectSource.NoMirroring : ShaderEffectSource.MirrorVertically
                transform: Scale {
                    origin.y: host.height / 2
                    yScale: host.softwareRendering ? -1 : 1
                }
                hideSource: true
                live: true
            }
        }
    }
}
