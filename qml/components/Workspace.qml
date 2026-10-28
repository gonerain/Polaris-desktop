pragma ComponentBehavior: Bound

import QtQuick

// One allocator and one canvas. Components reserve shapes, never separate pages.
Item {
    id: workspace
    required property var shell
    required property var presenter
    required property var taskStore
    required property var agentHub
    required property var componentApi
    property var calendarHandle: null
    property var agentHandle: null
    readonly property var componentBoard: board

    function requestComponent(url, cells, properties) {
        const factory = Qt.createComponent(url)
        if (factory.status !== Component.Ready) {
            console.error("组件加载失败", url, factory.errorString())
            return null
        }
        const handle = board.request(factory, {cells: cells}, properties)
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

    Component.onCompleted: {
        calendarHandle = requestComponent("CalendarTasks.qml", [[0, 0], [1, 0]],
            {taskStore: taskStore, objectName: "calendarTasks"})
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
             obscured: Qt.binding(function() { return workspace.presenter.busy })})
        if (agentHandle) {
            agentHandle.item.expandRequested.connect(openAgentDetails)
            agentHandle.item.dragActiveChanged.connect(function(active) {
                workspace.shell.setWorkspaceMoving(active, false)
            })
        }
    }

    ComponentBoard {
        id: board
        objectName: "componentBoard"
        width: workspace.presenter.busy ? workspace.presenter.savedGeometry.width : parent.width
        height: workspace.presenter.busy ? workspace.presenter.savedGeometry.height : parent.height
        presenter: workspace.presenter
        panelSize: Qt.size(260, 260)
        panelCount: 4
        gap: 8
    }
    WindowResizeHandles {
        objectName: "resizeHandles"
        z: 10
        anchors.fill: parent
        targetWindow: workspace.shell
        enabled: !workspace.shell.collapsing && !workspace.presenter.busy
    }
}
