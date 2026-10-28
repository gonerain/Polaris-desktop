pragma ComponentBehavior: Bound

import QtQuick
import "Theme.js" as Theme

// One allocator and one canvas. Components reserve shapes, never separate pages.
Rectangle {
    id: workspace
    objectName: "canvasBackground"
    color: "#E9EDF3"
    radius: 16
    border.color: "#CBD5E1"
    required property var shell
    required property var presenter
    required property var taskStore
    required property var agentHub
    required property var componentApi
    required property var weixinClient
    required property var weixinChat
    property var calendarHandle: null
    property var agentHandle: null
    property var weixinHandle: null
    readonly property var componentBoard: board

    function requestComponent(url, cells, properties, title) {
        const factory = Qt.createComponent(url)
        if (factory.status !== Component.Ready) {
            console.error("组件加载失败", url, factory.errorString())
            return null
        }
        const handle = board.request(factory, {cells: cells, title: title}, properties)
        if (!handle.ok) {
            console.error("组件申请 cell 失败", url, handle.error)
            return null
        }
        handle.factory = factory
        return handle
    }

    function openAgentDetails() {
        return agentHandle && board.present(agentHandle, agentHandle.factory,
            {span: Qt.size(3, 2)}, {hub: agentHub, components: componentApi, detailed: true,
                                   objectName: "agentFullView"})
    }

    function openWeixinDetails() {
        return weixinHandle && board.present(weixinHandle, weixinHandle.factory,
            {span: Qt.size(2, 2)}, {client: weixinClient, chat: weixinChat, detailed: true,
                                   objectName: "weixinFullView"})
    }

    Component.onCompleted: {
        calendarHandle = requestComponent("CalendarTasks.qml", [[0, 0], [1, 0]],
            {taskStore: taskStore, objectName: "calendarTasks"}, qsTr("日程"))
        if (calendarHandle) {
            calendarHandle.item.focusRequested.connect(function(factory, options, properties) {
                board.presentItem(calendarHandle.item, factory, options, properties)
            })
            calendarHandle.item.dragActiveChanged.connect(function(active) {
                workspace.shell.setWorkspaceMoving(active, false)
            })
        }
        agentHandle = requestComponent("AgentPanel.qml", [[0, 0]],
            {hub: agentHub, components: componentApi, objectName: "agentPanel",
             obscured: Qt.binding(function() { return workspace.presenter.busy })}, qsTr("Agent"))
        if (agentHandle) {
            agentHandle.item.expandRequested.connect(openAgentDetails)
            agentHandle.item.dragActiveChanged.connect(function(active) {
                workspace.shell.setWorkspaceMoving(active, false)
            })
        }
        weixinHandle = requestComponent("WeixinPanel.qml", [[0, 0]],
            {client: weixinClient, chat: weixinChat, objectName: "weixinPanel"}, qsTr("微信"))
        if (weixinHandle) weixinHandle.item.expandRequested.connect(openWeixinDetails)
    }

    MouseArea {
        id: canvasMoveArea
        objectName: "canvasMoveArea"
        z: 2
        containmentMask: QtObject {
            function contains(point: point): bool {
                const local = board.mapFromItem(canvasMoveArea, point.x, point.y)
                return !board.containsComponentAt(local)
            }
        }
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        cursorShape: workspace.shell.canvasMoving ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        enabled: (!board.layoutLocked || workspace.shell.canvasMoving) && !board.dragging && !board.settling
        onPressed: function(mouse) {
            const controls = mapToItem(zoomControls, mouse.x, mouse.y)
            if (controls.x >= 0 && controls.y >= 0 && controls.x < zoomControls.width && controls.y < zoomControls.height)
                return
            workspace.shell.canvasMoving = true
            workspace.shell.setWorkspaceMoving(true, true)
        }
        onReleased: finishMove()
        onCanceled: finishMove()
        function finishMove() {
            workspace.shell.canvasMoving = false
            workspace.shell.setWorkspaceMoving(board.dragging || board.settling, false)
        }
    }
    Item {
        z: 3
        x: workspace.shell.canvasPadding
        y: 6
        width: parent.width - 2 * workspace.shell.canvasPadding
        height: workspace.shell.canvasHeaderHeight
        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: qsTr("⠿  画布 · 拖动背景移动")
            color: "#64748B"
            font.pixelSize: 11
        }
        Row {
            id: zoomControls
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            IconButton {
                objectName: "canvasZoomOutButton"
                text: "−"
                tooltip: qsTr("缩小画布")
                enabled: workspace.shell.canZoomCanvas(workspace.shell.canvasZoom - 0.1)
                onClicked: workspace.shell.zoomCanvas(workspace.shell.canvasZoom - 0.1)
            }
            IconButton {
                objectName: "canvasZoomResetButton"
                text: Math.round(workspace.shell.canvasZoom * 100) + "%"
                textSize: 11
                tooltip: qsTr("恢复100%")
                enabled: workspace.shell.canZoomCanvas(1)
                onClicked: workspace.shell.zoomCanvas(1)
            }
            IconButton {
                objectName: "canvasZoomInButton"
                text: "+"
                tooltip: qsTr("放大画布")
                enabled: workspace.shell.canZoomCanvas(workspace.shell.canvasZoom + 0.1)
                onClicked: workspace.shell.zoomCanvas(workspace.shell.canvasZoom + 0.1)
            }
        }
    }

    ComponentBoard {
        id: board
        objectName: "componentBoard"
        x: workspace.shell.canvasPadding
        y: workspace.shell.canvasPadding + workspace.shell.canvasHeaderHeight
        width: ((workspace.presenter.busy ? workspace.presenter.savedGeometry.width : parent.width)
                - 2 * workspace.shell.canvasPadding) / workspace.shell.canvasZoom
        height: ((workspace.presenter.busy ? workspace.presenter.savedGeometry.height : parent.height)
                 - workspace.shell.canvasHeaderHeight - 2 * workspace.shell.canvasPadding) / workspace.shell.canvasZoom
        scale: workspace.shell.canvasZoom
        transformOrigin: Item.TopLeft
        presenter: workspace.presenter
        panelSize: Qt.size(260, 260)
        panelCount: 4
        gap: 8
        interactionsEnabled: !workspace.shell.editorPopupCount && !workspace.shell.quitConfirmationVisible
                             && !workspace.shell.collapsing && !workspace.shell.canvasMoving
        onDraggingChanged: workspace.shell.setWorkspaceMoving(dragging || settling, false)
        onSettlingChanged: workspace.shell.setWorkspaceMoving(dragging || settling, false)
    }
    WindowResizeHandles {
        objectName: "resizeHandles"
        z: 10
        anchors.fill: parent
        targetWindow: workspace.shell
        enabled: !board.layoutLocked && !board.dragging && !board.settling
    }
}
