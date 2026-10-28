pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

Rectangle {
    id: root
    required property var taskStore
    readonly property var presentation: parent.presentationContext
    property string mode: "todo"
    property bool detailOpen: false
    readonly property bool escapeBlocked: composer.opened || detailOpen
        || (mode === "todo" && overview.escapeBlocked)
    color: Theme.background
    radius: 12
    border.color: Theme.border
    border.width: 1
    clip: true
    Component.onCompleted: taskStore.goToday()

    function selectMode(value) {
        if (mode === value) return
        composer.dismissEditors()
        agenda.closeComposer()
        detailOpen = false
        mode = value
    }
    function beginTask() {
        if (mode === "todo") {
            taskStore.goToday()
            overview.scope = "today"
            composer.open()
        } else if (detailOpen) {
            composer.dismissEditors()
            agenda.openComposer()
        } else composer.open()
    }

    EditDismissArea { anchors.fill: parent }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.width >= 800 ? 24 : 14
        spacing: 16
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            DragHandler {
                target: null
                acceptedButtons: Qt.LeftButton
                onActiveChanged: {
                    const owner = root.Window.window
                    if (owner) {
                        owner.moving = active
                        if (active) owner.startSystemMove()
                    }
                }
            }
            IconButton {
                objectName: "focusBackButton"
                text: "←"
                buttonSize: 34
                accessibleName: qsTr("返回画布")
                tooltip: qsTr("返回画布 · Esc")
                onClicked: root.presentation.close()
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 5
                Text {
                    text: qsTr("我的日程")
                    color: Theme.ink
                    font.pixelSize: 23
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTr("专注今天，也看见接下来的安排")
                    color: Theme.muted
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            Text {
                visible: root.width > 700
                text: Qt.formatDate(new Date(), "yyyy年M月d日")
                color: Theme.muted
                font.pixelSize: 11
                Layout.rightMargin: 10
            }
            IconButton {
                objectName: "focusAddTask"
                text: qsTr("＋ 添加待办")
                filled: true
                buttonSize: 36
                textSize: 12
                onClicked: root.beginTask()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Rectangle {
                implicitWidth: modes.implicitWidth + 8
                implicitHeight: 42
                radius: 11
                color: "#EBEEF6"
                RowLayout {
                    id: modes
                    anchors.centerIn: parent
                    spacing: 4
                    Repeater {
                        model: [{key: "todo", title: qsTr("待办清单")},
                            {key: "week", title: qsTr("周日程")}, {key: "month", title: qsTr("月日程")}]
                        IconButton {
                            required property var modelData
                            objectName: "focusMode_" + modelData.key
                            text: modelData.title
                            buttonSize: 34
                            textSize: 12
                            selected: root.mode === modelData.key
                            onClicked: root.selectMode(modelData.key)
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                visible: root.width >= 780
                text: root.mode === "todo" ? qsTr("把重要的事，一件件做好")
                    : root.mode === "week" ? qsTr("看清这一周的节奏") : qsTr("为这个月留好空间")
                color: Theme.muted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            Item { Layout.fillWidth: true; visible: root.width < 780 }
            IconButton {
                visible: root.mode !== "todo"
                text: qsTr("当天详情")
                textSize: 11
                buttonSize: 30
                selected: root.detailOpen
                onClicked: {
                    composer.dismissEditors()
                    root.detailOpen = !root.detailOpen
                }
            }
        }
        Text {
            visible: composer.opened
            text: qsTr("添加到 ") + root.taskStore.dateLabel(root.taskStore.selectedDate)
            color: Theme.primary
            font.pixelSize: 11
        }
        TaskComposer {
            id: composer
            objectName: "focusComposer"
            Layout.fillWidth: true
            taskStore: root.taskStore
        }
        TaskOverview {
            id: overview
            objectName: "taskOverview"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.maximumWidth: 900
            Layout.alignment: Qt.AlignHCenter
            visible: root.mode === "todo"
            taskStore: root.taskStore
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.mode !== "todo"
            columns: root.width >= 900 ? 2 : 1
            columnSpacing: 16
            rowSpacing: 12
            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                active: root.mode !== "todo"
                sourceComponent: ScheduleView {
                    objectName: "focusSchedule"
                    taskStore: root.taskStore
                    weekMode: root.mode === "week"
                    onDayActivated: function(date, addTask) {
                        composer.dismissEditors()
                        root.taskStore.selectDate(date)
                        root.detailOpen = true
                        if (addTask) Qt.callLater(function() { agenda.openComposer() })
                    }
                }
            }
            Rectangle {
                visible: root.detailOpen
                Layout.preferredWidth: 330
                Layout.fillWidth: root.width < 900
                Layout.fillHeight: root.width >= 900
                Layout.preferredHeight: root.width < 900 ? Math.min(280, root.height * 0.42) : -1
                radius: 12
                color: Theme.surface
                border.color: Theme.border
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: qsTr("当天安排")
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                        IconButton {
                            text: "×"
                            buttonSize: 24
                            accessibleName: qsTr("收起当天详情")
                            onClicked: root.detailOpen = false
                        }
                    }
                    AgendaPanel {
                        id: agenda
                        objectName: "focusAgenda"
                        showCalendarButton: false
                        taskStore: root.taskStore
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumWidth: 0
                    }
                }
            }
        }
        StoreStatus { Layout.fillWidth: true; taskStore: root.taskStore }
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: root.visible && !(root.detailOpen && root.mode !== "todo")
        onActivated: root.beginTask()
    }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.detailOpen && !agenda.composerOpen
                 && !(root.Window.window && root.Window.window.editorPopupCount > 0)
        onActivated: root.detailOpen = false
    }
    Shortcut {
        sequence: "Alt+Left"
        enabled: root.visible && root.mode !== "todo" && !root.detailOpen
        onActivated: root.mode === "week" ? root.taskStore.changeDay(-7) : root.taskStore.changeMonth(-1)
    }
    Shortcut {
        sequence: "Alt+Right"
        enabled: root.visible && root.mode !== "todo" && !root.detailOpen
        onActivated: root.mode === "week" ? root.taskStore.changeDay(7) : root.taskStore.changeMonth(1)
    }
    Shortcut {
        sequence: "Ctrl+T"
        enabled: root.visible && !root.detailOpen
        onActivated: root.taskStore.goToday()
    }
}
