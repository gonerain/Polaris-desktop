pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

ColumnLayout {
    id: root

    property var taskStore
    property bool composerOpen: false
    property bool timeError: false
    property bool showFocusButton: false
    property bool showCalendarButton: true
    signal focusRequested()
    signal calendarRequested()
    signal dragActiveChanged(bool active)

    spacing: 12

    RowLayout {
        id: header
        Layout.fillWidth: true
        spacing: 12

        DragHandler {
            objectName: "agendaMoveHandler"
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: {
                root.dragActiveChanged(active)
                if (active && Window.window)
                    Window.window.startSystemMove()
            }
        }

        IconButton {
            text: "‹"
            buttonSize: 22
            textSize: 18
            accessibleName: qsTr("前一天")
            tooltip: qsTr("前一天 · Alt+←")
            onClicked: if (root.taskStore) root.taskStore.changeDay(-1)
        }

        Text {
            Layout.alignment: Qt.AlignVCenter
            text: root.taskStore ? root.taskStore.selectedDayNumber : ""
            color: Theme.ink
            font.pixelSize: 32
            font.weight: Font.DemiBold
        }

        IconButton {
            text: "›"
            buttonSize: 22
            textSize: 18
            accessibleName: qsTr("后一天")
            tooltip: qsTr("后一天 · Alt+→")
            onClicked: if (root.taskStore) root.taskStore.changeDay(1)
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 2

            Text {
                Layout.fillWidth: true
                text: root.taskStore ? root.taskStore.selectedWeekday : ""
                color: Theme.ink
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: root.taskStore
                    ? root.taskStore.selectedDateLabel
                        + (root.taskStore.taskCount > 0
                            ? " · " + root.taskStore.taskCount + qsTr(" 项")
                            : "")
                    : ""
                color: Theme.muted
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        IconButton {
            visible: !!root.taskStore && root.taskStore.selectedDate !== root.taskStore.todayDate
            text: qsTr("今")
            buttonSize: 24
            textSize: 11
            accessibleName: qsTr("回到今天")
            tooltip: qsTr("回到今天 · Ctrl+T")
            onClicked: root.taskStore.goToday()
        }

        IconButton {
            objectName: "openFocusButton"
            visible: root.showFocusButton
            text: "↗"
            buttonSize: 28
            accessibleName: qsTr("打开日程总览")
            tooltip: qsTr("日程总览")
            onClicked: {
                root.closeComposer()
                root.focusRequested()
            }
        }

        IconButton {
            objectName: "openCalendarButton"
            visible: root.showCalendarButton
            text: qsTr("月历")
            textSize: 10
            buttonSize: 28
            accessibleName: qsTr("打开月历")
            tooltip: qsTr("打开月历")
            onClicked: {
                root.closeComposer()
                root.calendarRequested()
            }
        }

        IconButton {
            objectName: "openComposerButton"
            text: root.composerOpen ? "×" : "+"
            textSize: root.composerOpen ? 16 : 20
            buttonSize: 32
            filled: !root.composerOpen
            accessibleName: root.composerOpen ? qsTr("关闭") : qsTr("添加")
            tooltip: root.composerOpen ? qsTr("关闭") : qsTr("添加")
            onClicked: root.toggleComposer()
        }
    }

    Item {
        id: composerWrapper
        readonly property bool editBoundary: true

        property real targetHeight: root.composerOpen ? 42 : 0

        Layout.fillWidth: true
        Layout.preferredHeight: targetHeight
        visible: targetHeight > 0 || root.composerOpen
        opacity: root.composerOpen ? 1 : 0
        clip: true

        Behavior on targetHeight {
            NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
        }

        Behavior on opacity {
            NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 42
            radius: 10
            color: "#F8FAFC"
            border.width: 1
            border.color: addBarHover.hovered ? "#DDE3FF" : Theme.border

            Behavior on border.color {
                ColorAnimation { duration: Theme.fast }
            }

            HoverHandler {
                id: addBarHover
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 5
                anchors.rightMargin: 4
                spacing: 4

                TimeField {
                    id: newTime
                    objectName: "newTaskTimeInput"
                    Layout.preferredWidth: 48
                    Layout.minimumWidth: 44
                    Layout.maximumWidth: 52
                    chip: true
                    error: root.timeError
                    placeholderText: qsTr("时间")
                    horizontalAlignment: TextInput.AlignHCenter
                    font.pixelSize: 10
                    onTimeSelected: function(value) { text = value; root.timeError = false }
                    onTextEdited: root.timeError = false
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 14
                    color: Theme.border
                }

                InlineField {
                    id: newTask
                    objectName: "newTaskInput"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    bare: true
                    placeholderText: qsTr("添加…")
                    font.pixelSize: 12
                    onAccepted: root.addTask()
                }

                IconButton {
                    objectName: "addTaskButton"
                    text: "+"
                    filled: true
                    textSize: 16
                    buttonSize: 26
                    accessibleName: qsTr("保存")
                    tooltip: qsTr("保存")
                    onClicked: root.addTask()
                }
            }
        }
    }

    Text {
        visible: root.timeError
        Layout.leftMargin: 4
        Layout.preferredHeight: visible ? 12 : 0
        text: qsTr("时间格式应为 HH:mm")
        color: Theme.danger
        font.pixelSize: 9
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ListView {
            id: taskList
            anchors.fill: parent
            clip: true
            spacing: 4
            model: root.taskStore ? root.taskStore.tasks : []
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            displaced: Transition {
                NumberAnimation { properties: "y"; duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            delegate: TaskCard {
                required property var modelData
                width: taskList.width
                entry: modelData
                taskStore: root.taskStore
                animateEntrance: root.taskStore && root.taskStore.lastAddedTaskId === modelData.entryId
            }

            ScrollBar.vertical: ScrollBar {
                id: verticalScroll
                readonly property bool editBoundary: true
                policy: ScrollBar.AsNeeded
                width: 4

                contentItem: Rectangle {
                    implicitWidth: 3
                    implicitHeight: 20
                    radius: 1.5
                    color: verticalScroll.pressed ? Theme.primary : "#DDE3EE"
                    visible: verticalScroll.size < 1
                }

                background: Item {}
            }
        }
    }

    Connections {
        target: root.taskStore

        function onSelectedDateChanged() {
            taskList.positionViewAtBeginning()
            taskList.opacity = 0
            header.opacity = 0.35
            dateEnter.restart()
        }
    }

    ParallelAnimation {
        id: dateEnter

        NumberAnimation {
            target: taskList
            property: "opacity"
            from: 0
            to: 1
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }

        NumberAnimation {
            target: header
            property: "opacity"
            from: 0.35
            to: 1
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }
    }

    Shortcut {
        sequence: "Ctrl+N"
        enabled: root.visible && root.enabled
        onActivated: {
            if (!root.composerOpen) root.toggleComposer()
        }
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
    Shortcut {
        sequence: "Esc"
        enabled: root.composerOpen && root.visible && root.enabled
                 && !(root.Window.window && root.Window.window.editorPopupCount > 0)
        onActivated: root.closeComposer()
    }

    function toggleComposer() {
        if (root.composerOpen) {
            root.closeComposer()
            return
        }
        root.composerOpen = true
        Qt.callLater(function() { newTask.forceActiveFocus() })
    }

    function dismissEditors() {
        // Dismiss the UI, not the draft. Reopening + restores what was typed.
        root.composerOpen = false
        root.timeError = false
    }

    function closeComposer() {
        root.composerOpen = false
        root.timeError = false
        newTime.clear()
        newTask.clear()
    }

    function addTask() {
        if (!root.taskStore)
            return
        const title = newTask.text.trim()
        const timeValue = newTime.text.trim()
        if (!title) {
            newTask.forceActiveFocus()
            return
        }
        if (timeValue.length > 0 && !root.taskStore.isValidTime(timeValue)) {
            root.timeError = true
            newTime.forceActiveFocus()
            return
        }
        const entry = root.taskStore.addTask(title, timeValue)
        if (!entry)
            return
        root.closeComposer()
        Qt.callLater(function() {
            const tasks = root.taskStore ? root.taskStore.tasks : []
            const index = tasks.findIndex(function(task) { return task.entryId === entry.entryId })
            if (index >= 0)
                taskList.positionViewAtIndex(index, ListView.Contain)
        })
    }
}
