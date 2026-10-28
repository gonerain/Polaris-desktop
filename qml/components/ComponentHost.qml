pragma ComponentBehavior: Bound

import QtQuick
import Polaris 1.0
import "Theme.js" as Theme

RegionSurface {
    id: host
    required property var allocation
    required property var board
    property Item componentItem: null
    property string caption: qsTr("组件")
    property bool minimized: false
    property bool dragging: false
    property bool rejected: false
    property point pressPoint: Qt.point(0, 0)
    property point dragOffset: Qt.point(0, 0)
    readonly property int spanX: Math.max(...allocation.cells.map(cell => cell[0])) + 1
    readonly property int spanY: Math.max(...allocation.cells.map(cell => cell[1])) + 1
    readonly property real expandedHeight: spanY * board.cellHeight + (spanY - 1) * board.gap
    readonly property real headerHeight: Math.min(board.chromeHeight, board.cellHeight)
    readonly property real bodyHeight: Math.max(0, expandedHeight - headerHeight)
    readonly property real barX: allocation.cells[0][0] * (board.cellWidth + board.gap)
    readonly property real barWidth: {
        const first = allocation.cells[0][0]
        let end = first
        while (allocation.cells.some(cell => cell[0] === end + 1 && cell[1] === 0)) ++end
        return (end - first + 1) * board.cellWidth + (end - first) * board.gap
    }
    readonly property var bodyRegions: board.regionsFor(allocation.cells, board.cellWidth, board.cellHeight, board.gap)
        .map(function(rect) {
            const top = Math.max(host.headerHeight, rect.y)
            return {x: rect.x, y: top - host.headerHeight, width: rect.width,
                    height: Math.max(0, rect.y + rect.height - top)}
        }).filter(rect => rect.height > 0)
    readonly property bool rectangular: regions.length === 1
    readonly property bool softwareRendering: GraphicsInfo.api === GraphicsInfo.Software
    x: allocation.origin[0] * (board.cellWidth + board.gap) + dragOffset.x
    y: allocation.origin[1] * (board.cellHeight + board.gap) + dragOffset.y
    width: spanX * board.cellWidth + (spanX - 1) * board.gap
    height: minimized ? headerHeight : expandedHeight
    clip: rectangular
    z: dragging ? 100 : 0
    opacity: dragging ? 0.85 : 1
    regions: minimized ? [{x: barX, y: 0, width: barWidth, height: headerHeight}]
                       : board.regionsFor(allocation.cells, board.cellWidth, board.cellHeight, board.gap)
    visible: false

    function instantiate(factory: Component, properties: var): bool {
        const initial = Object.assign({}, properties || {}, {x: 0, y: 0, width: host.width, height: host.bodyHeight})
        const object = factory.createObject(source, initial)
        const created = object as Item
        if (!created) {
            if (object) object.destroy()
            return false
        }
        componentItem = created
        created.width = Qt.binding(function() { return host.width })
        created.height = Qt.binding(function() { return host.bodyHeight })
        visible = true
        return true
    }

    function updateMove(point) {
        const dx = point.x - pressPoint.x
        const dy = point.y - pressPoint.y
        if (!dragging) {
            if (dx * dx + dy * dy < 36) return
            forceActiveFocus()
            dragging = true
            board.dragging = true
        }
        dragOffset = Qt.point(dx, dy)
    }
    function finishMove(cancelled) {
        const moving = dragging
        const accepted = !moving || (!cancelled && board.finishDrag(host))
        dragOffset = Qt.point(0, 0)
        dragging = false
        board.dragging = false
        if (moving && !accepted) { rejected = true; rejectionTimer.restart() }
    }
    Timer { id: rejectionTimer; interval: 500; onTriggered: host.rejected = false }

    Item {
        id: scene
        anchors.fill: parent
        Item {
            id: source
            y: host.headerHeight
            width: host.width
            height: host.bodyHeight
            visible: !host.minimized
            readonly property var panelContext: ({
                width: host.width, height: host.bodyHeight,
                cells: host.allocation.cells, regions: host.bodyRegions,
                outerRegions: host.regions, headerHeight: host.headerHeight,
                minimized: host.minimized
            })
        }
        Rectangle {
            id: titleBar
            objectName: "componentTitleBar"
            x: host.barX
            width: host.barWidth
            height: host.headerHeight
            radius: 8
            color: host.dragging ? Theme.primarySoft : Theme.surface
            border.color: host.rejected ? Theme.danger : Theme.border
            clip: true
            Text {
                x: 10
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - 48)
                text: "⠿  " + host.caption
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: host.dragging ? Theme.primary : Theme.muted
                elide: Text.ElideRight
            }
            MouseArea {
                objectName: "componentMoveArea"
                anchors.left: parent.left
                anchors.right: minimizeButton.left
                height: parent.height
                enabled: !host.board.layoutLocked && (!host.board.dragging || host.dragging)
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                cursorShape: host.dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                onPressed: function(mouse) { host.pressPoint = mapToItem(host.board, mouse.x, mouse.y) }
                onPositionChanged: function(mouse) {
                    if (pressed) host.updateMove(mapToItem(host.board, mouse.x, mouse.y))
                }
                onReleased: function(mouse) {
                    host.updateMove(mapToItem(host.board, mouse.x, mouse.y))
                    host.finishMove(false)
                }
                onCanceled: host.finishMove(true)
            }
            Rectangle {
                id: minimizeButton
                objectName: "componentMinimizeButton"
                anchors.right: parent.right
                anchors.rightMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                width: 24
                height: 24
                radius: 5
                color: buttonHover.hovered || activeFocus ? Theme.primarySoft : Theme.clearSurface
                enabled: !host.board.layoutLocked && !host.board.dragging
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: host.minimized ? qsTr("恢复组件") : qsTr("最小化组件")
                Text {
                    anchors.centerIn: parent
                    text: host.minimized ? "+" : "−"
                    color: Theme.primary
                    font.pixelSize: 16
                }
                HoverHandler { id: buttonHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: host.board.setMinimized(host.board.handleFor(host), !host.minimized) }
                Keys.onReturnPressed: host.board.setMinimized(host.board.handleFor(host), !host.minimized)
                Keys.onSpacePressed: host.board.setMinimized(host.board.handleFor(host), !host.minimized)
            }
        }
    }

    // Capture the frame and content once per shape fragment, preserving holes.
    Repeater {
        model: host.rectangular ? [] : host.regions
        Item {
            required property var modelData
            x: modelData.x
            y: modelData.y
            width: modelData.width
            height: modelData.height
            clip: true
            ShaderEffectSource {
                x: -parent.x
                y: -parent.y
                width: host.width
                height: host.height
                sourceItem: scene
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
