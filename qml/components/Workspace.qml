pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

// Created on the first expansion, then retained so drafts and focus views survive.
Item {
    id: workspace
    required property var shell
    required property var presenter
    required property var taskStore
    required property var agentHub
    required property var componentApi
    property var calendarFactory: null
    property var calendarHandle: null
    readonly property var componentBoard: board

    function ensurePage() {
        if (shell.selectedPage === "agents") {
            if (!agentLoader.source.toString())
                agentLoader.setSource("AgentPanel.qml", {hub: agentHub, components: componentApi, objectName: "agentPanel"})
            return
        }
        if (calendarHandle)
            return
        // A URL, rather than an inline CalendarTasks type, defers its imports too.
        if (!calendarFactory)
            calendarFactory = Qt.createComponent("CalendarTasks.qml")
        if (calendarFactory.status !== Component.Ready) {
            console.error("日程界面加载失败", calendarFactory.errorString())
            return
        }
        const result = board.request(calendarFactory, {cells: [[0, 0], [1, 0]]}, {taskStore: taskStore, objectName: "calendarTasks"})
        if (!result.ok) {
            console.error("初始化画板失败", result.error)
            return
        }
        calendarHandle = result
        result.item.focusRequested.connect(function(factory, options, properties) {
            board.presentItem(result.item, factory, options, properties)
        })
        result.item.dragActiveChanged.connect(function(active) {
            workspace.shell.setWorkspaceMoving(active, false)
        })
    }

    Connections {
        target: workspace.shell
        function onSelectedPageChanged() { workspace.ensurePage() }
    }
    Component.onCompleted: ensurePage()

    Rectangle {
        width: parent.width
        height: workspace.shell.navigationHeight
        radius: 8
        color: Theme.surface
        border.color: Theme.border
        DragHandler {
            objectName: "componentNavigationDrag"
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: workspace.shell.setWorkspaceMoving(active, true)
        }
    }
    Row {
        height: workspace.shell.navigationHeight
        spacing: 4
        enabled: !workspace.presenter.busy
        Button {
            id: calendarNavigation
            objectName: "calendarPageButton"
            text: qsTr("日程")
            height: workspace.shell.navigationHeight - 2
            width: 72
            background: Rectangle { radius: 7; color: workspace.shell.selectedPage === "calendar" ? Theme.primarySoft : Theme.surface }
            contentItem: Text {
                text: calendarNavigation.text
                font.pixelSize: 12
                color: workspace.shell.selectedPage === "calendar" ? Theme.primary : Theme.muted
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: workspace.shell.showPage("calendar")
        }
        Button {
            id: agentNavigation
            objectName: "agentPageButton"
            text: qsTr("Agent") + (workspace.agentHub && workspace.agentHub.unreadCount ? " · " + workspace.agentHub.unreadCount : "")
            height: workspace.shell.navigationHeight - 2
            width: 100
            background: Rectangle { radius: 7; color: workspace.shell.selectedPage === "agents" ? Theme.primarySoft : Theme.surface }
            contentItem: Text {
                text: agentNavigation.text
                font.pixelSize: 12
                color: workspace.shell.selectedPage === "agents" ? Theme.primary : Theme.muted
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: workspace.shell.showPage("agents")
        }
    }

    Loader {
        id: agentLoader
        x: 0
        y: workspace.shell.navigationHeight
        width: parent.width
        height: parent.height - workspace.shell.navigationHeight
        visible: workspace.shell.selectedPage === "agents"
    }
    ComponentBoard {
        id: board
        objectName: "componentBoard"
        width: workspace.presenter.busy ? workspace.presenter.savedGeometry.width : parent.width
        y: workspace.shell.navigationHeight
        height: (workspace.presenter.busy ? workspace.presenter.savedGeometry.height : parent.height) - workspace.shell.navigationHeight
        visible: workspace.shell.selectedPage === "calendar"
        presenter: workspace.presenter
        panelSize: Qt.size(260, 260)
        panelCount: 2
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
