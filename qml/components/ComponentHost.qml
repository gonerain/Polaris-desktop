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
    property point pressPoint: Qt.point(0, 0)
    property point pointerPoint: Qt.point(0, 0)
    property string moveAxis: ""
    property int pressColumn: 0
    property int pressRow: 0
    property real displayColumn: allocation.origin[0]
    property real displayRow: allocation.origin[1]
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
    x: displayColumn * (board.cellWidth + board.gap)
    y: displayRow * (board.cellHeight + board.gap)
    width: spanX * board.cellWidth + (spanX - 1) * board.gap
    height: minimized ? headerHeight : expandedHeight
    clip: rectangular
    z: board.movingHost === host ? 1 : 0
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

    Behavior on displayColumn {
        enabled: host.visible && host.board.settling
        NumberAnimation { duration: host.board.moveDuration; easing.type: Easing.OutCubic }
    }
    Behavior on displayRow {
        enabled: host.visible && host.board.settling
        NumberAnimation { duration: host.board.moveDuration; easing.type: Easing.OutCubic }
    }

    function beginMove(point) {
        pressPoint = point
        pointerPoint = point
        moveAxis = ""
        pressColumn = allocation.origin[0]
        pressRow = allocation.origin[1]
    }
    function updateMove(point, finalStep) {
        pointerPoint = point
        const dx = Math.abs(point.x - pressPoint.x)
        const dy = Math.abs(point.y - pressPoint.y)
        if (!dragging) {
            const canX = board.columns > spanX
            const canY = board.rows > spanY
            if (canX && dx >= 8 && (!canY || dx > dy * 1.2)) moveAxis = "x"
            else if (canY && dy >= 8 && (!canX || dy > dx * 1.2)) moveAxis = "y"
            else return
            forceActiveFocus()
            dragging = true
            board.activeDragHost = host
            board.dragging = true
        }
        board.hoverStep(host, point, finalStep)
    }
    function finishMove() {
        dragging = false
        moveAxis = ""
        if (board.activeDragHost === host) {
            board.activeDragHost = null
            board.dragging = false
        }
    }

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
            border.color: host.dragging ? Theme.primary : Theme.border
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
                         && (!host.board.settling || host.dragging)
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                cursorShape: host.moveAxis === "x" ? Qt.SizeHorCursor : host.moveAxis === "y" ? Qt.SizeVerCursor
                             : host.board.columns === host.spanX ? Qt.SizeVerCursor
                             : host.board.rows === host.spanY ? Qt.SizeHorCursor : Qt.OpenHandCursor
                onPressed: function(mouse) { host.beginMove(mapToItem(host.board, mouse.x, mouse.y)) }
                onPositionChanged: function(mouse) {
                    if (pressed) host.updateMove(mapToItem(host.board, mouse.x, mouse.y), false)
                }
                onReleased: function(mouse) {
                    host.updateMove(mapToItem(host.board, mouse.x, mouse.y), true)
                    host.finishMove()
                }
                onCanceled: host.finishMove()
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
                enabled: !host.board.layoutLocked && !host.board.dragging && !host.board.settling
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
