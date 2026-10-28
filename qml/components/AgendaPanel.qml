pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

ColumnLayout {
    id: root
    property var taskStore
    property alias composerOpen: composer.opened
    property bool showFocusButton: false
    property bool showCalendarButton: true
    property bool showCompleted: false
    readonly property var visibleTasks: taskStore ? taskStore.tasks.filter(function(task) {
        return root.showCompleted || !task.done
    }) : []
    TaskRowsModel {
        id: taskRows
        rows: root.visibleTasks.map(function(task) {
            return {task: task, date: root.taskStore.selectedDate, overdue: false}
        })
    }
    signal focusRequested()
    signal calendarRequested()
    signal dragActiveChanged(bool active)
    spacing: 10

    function toggleComposer() {
        if (composer.opened) composer.dismissEditors()
        else composer.open()
    }
    function openComposer() { composer.open() }
    function closeComposer() { composer.dismissEditors() }
    function dismissEditors() { composer.dismissEditors() }

    RowLayout {
        id: header
        Layout.fillWidth: true
        spacing: 8
        DragHandler {
            objectName: "agendaMoveHandler"
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: {
                root.dragActiveChanged(active)
                if (active && root.Window.window) root.Window.window.startSystemMove()
            }
        }
        IconButton {
            text: "‹"
            buttonSize: 22
            textSize: 18
            accessibleName: qsTr("前一天")
            onClicked: if (root.taskStore) root.taskStore.changeDay(-1)
        }
        Text {
            text: root.taskStore ? root.taskStore.selectedDayNumber : ""
            color: Theme.primary
            font.pixelSize: 32
            font.weight: Font.DemiBold
        }
        IconButton {
            text: "›"
            buttonSize: 22
            textSize: 18
            accessibleName: qsTr("后一天")
            onClicked: if (root.taskStore) root.taskStore.changeDay(1)
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 3
            Text {
                text: root.taskStore && root.taskStore.selectedDate === root.taskStore.todayDate
                    ? qsTr("我的一天") : qsTr("当天待办")
                color: Theme.ink
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: root.taskStore ? root.taskStore.selectedDateLabel + " · "
                    + root.taskStore.selectedWeekday + " · "
                    + (root.taskStore.taskCount - root.taskStore.completedCount) + qsTr(" 项") : ""
                color: Theme.muted
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }
        IconButton {
            visible: !!root.taskStore && root.taskStore.selectedDate !== root.taskStore.todayDate
            text: qsTr("今天")
            textSize: 10
            buttonSize: 26
            onClicked: root.taskStore.goToday()
        }
        IconButton {
            objectName: "openFocusButton"
            visible: root.showFocusButton
            text: "↗"
            buttonSize: 28
            accessibleName: qsTr("打开完整日程")
            tooltip: qsTr("待办、周日程与月日程")
            onClicked: { root.closeComposer(); root.focusRequested() }
        }
        IconButton {
            objectName: "openCalendarButton"
            visible: root.showCalendarButton
            text: qsTr("月历")
            textSize: 10
            buttonSize: 28
            onClicked: { root.closeComposer(); root.calendarRequested() }
        }
        IconButton {
            objectName: "openComposerButton"
            text: root.composerOpen ? "×" : "+"
            buttonSize: 30
            textSize: 18
            filled: !root.composerOpen
            accessibleName: qsTr("添加待办")
            onClicked: root.toggleComposer()
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 38
        visible: root.taskStore && root.taskStore.overdueCount > 0
        radius: 9
        color: Theme.accentSoft
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 4
            Text {
                Layout.fillWidth: true
                text: root.taskStore ? root.taskStore.overdueCount + qsTr(" 项待重新安排") : ""
                color: "#B76742"
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            IconButton {
                objectName: "compactMoveOverdue"
                text: qsTr("全部加入今天")
                textSize: 10
                buttonSize: 28
                onClicked: { root.taskStore.moveOverdueToToday(); root.taskStore.goToday() }
            }
        }
    }

    TaskComposer {
        id: composer
        Layout.fillWidth: true
        taskStore: root.taskStore
        onSubmitted: function(entryId) {
            Qt.callLater(function() {
                const index = root.visibleTasks.findIndex(function(task) { return task.entryId === entryId })
                if (index >= 0) taskList.positionViewAtIndex(index, ListView.Contain)
            })
        }
    }

    ListView {
        id: taskList
        objectName: "agendaTaskList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 4
        model: taskRows
        boundsBehavior: Flickable.StopAtBounds
        delegate: TaskCard {
            required property var task
            width: taskList.width
            entry: task
            taskStore: root.taskStore
            animateEntrance: root.taskStore.lastAddedTaskId === task.entryId
        }
        ScrollBar.vertical: ScrollBar {
            readonly property bool editBoundary: true
            policy: ScrollBar.AsNeeded
            width: 4
        }
        Column {
            anchors.centerIn: parent
            visible: taskList.count === 0 && !root.composerOpen
            spacing: 8
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "✓"
                font.pixelSize: 25
                color: "#C7CFEB"
            }
            Text {
                text: qsTr("没有待办，给今天留一点从容")
                color: Theme.muted
                font.pixelSize: 11
            }
        }
    }
    IconButton {
        Layout.alignment: Qt.AlignLeft
        visible: root.taskStore && root.taskStore.completedCount > 0
        text: root.showCompleted ? qsTr("收起已完成")
            : qsTr("已完成 ") + (root.taskStore ? root.taskStore.completedCount : 0) + qsTr(" 项 ›")
        textSize: 10
        buttonSize: 24
        onClicked: root.showCompleted = !root.showCompleted
    }
    Connections {
        target: root.taskStore
        function onSelectedDateChanged() { taskList.positionViewAtBeginning() }
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: root.visible && root.enabled
        onActivated: composer.open()
    }
    Shortcut {
        sequence: "Ctrl+T"
        enabled: root.visible && root.enabled
        onActivated: if (root.taskStore) root.taskStore.goToday()
    }
    Shortcut {
        sequence: "Alt+Left"
        enabled: root.visible && root.enabled
        onActivated: if (root.taskStore) root.taskStore.changeDay(-1)
    }
    Shortcut {
        sequence: "Alt+Right"
        enabled: root.visible && root.enabled
        onActivated: if (root.taskStore) root.taskStore.changeDay(1)
    }
}
