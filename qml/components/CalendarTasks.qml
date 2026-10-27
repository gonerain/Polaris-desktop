pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Polaris 1.0

Rectangle {
    id: widget
    implicitWidth: 528
    implicitHeight: 260
    color: "white"
    radius: 8
    border.color: "#e3e8ef"
    readonly property var taskStore: store
    // 宽度和任务区随窗口伸展；日期格高度适度增长并封顶，避免被拉成长条。
    readonly property real dayHeight: Math.max(28, Math.min(44, (height - 84) / 6))

    CalendarTaskStore {
        id: store
        objectName: "calendarTaskStore"
    }

    component SmallButton: AbstractButton {
        id: button
        property bool destructive: false
        property color textColor: destructive ? "#c44d59" : "#526075"
        implicitWidth: Math.max(24, label.implicitWidth + 12)
        implicitHeight: 26
        hoverEnabled: true
        background: Rectangle {
            radius: 5
            color: button.down ? "#dbe3ee" : (button.hovered ? "#edf1f7" : "transparent")
        }
        contentItem: Text {
            id: label
            text: button.text
            color: button.textColor
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    component EditorField: TextField {
        implicitHeight: 28
        font.pixelSize: 12
        selectByMouse: true
        leftPadding: 6
        rightPadding: 6
        background: Rectangle {
            radius: 4
            color: "white"
            border.color: parent.activeFocus ? "#7b9fda" : "#e3e8ef"
        }
    }

    function commit(entry: var, field: TextField) {
        if (!entry)
            return
        entry.rename(field.text)
        field.text = Qt.binding(function() { return entry.title })
    }

    function addTask() {
        if (store.addTask(newTask.text)) {
            newTask.clear()
            newTask.forceActiveFocus()
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 12

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            Layout.minimumWidth: 0
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: store.monthLabel
                    color: "#334155"
                    font.pixelSize: 13
                    font.weight: Font.Medium
                    Layout.fillWidth: true
                }
                SmallButton {
                    objectName: "previousMonthButton"
                    text: "‹"
                    Accessible.name: qsTr("上个月")
                    onClicked: store.changeMonth(-1)
                }
                SmallButton {
                    objectName: "nextMonthButton"
                    text: "›"
                    Accessible.name: qsTr("下个月")
                    onClicked: store.changeMonth(1)
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                GridLayout {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    columns: 7
                    columnSpacing: 2
                    rowSpacing: 2

                    Repeater {
                        model: ["一", "二", "三", "四", "五", "六", "日"]
                        Text {
                            required property string modelData
                            text: modelData
                            color: "#94a3b8"
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 18
                        }
                    }

                    Repeater {
                        model: store.calendarCells
                        SmallButton {
                            id: dayButton
                            required property var modelData
                            objectName: "calendarDay" + modelData.date
                            enabled: modelData.date !== ""
                            text: String(modelData.day)
                            textColor: modelData.selected ? "white" : (modelData.inMonth ? "#475569" : "#b7c0ce")
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            implicitHeight: widget.dayHeight
                            Accessible.name: modelData.date
                            background: Rectangle {
                                radius: 5
                                color: dayButton.modelData.selected ? "#648bc6"
                                    : (dayButton.hovered ? "#edf1f7" : (dayButton.modelData.today ? "#eaf0f9" : "transparent"))
                            }
                            onClicked: store.selectDate(modelData.date)
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            Layout.minimumWidth: 0
            spacing: 6

            Text {
                text: store.selectedDate + qsTr(" · 任务")
                color: "#334155"
                font.pixelSize: 12
                font.weight: Font.Medium
                Layout.preferredHeight: 26
                verticalAlignment: Text.AlignVCenter
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 3
                EditorField {
                    id: newTask
                    objectName: "newTaskInput"
                    placeholderText: qsTr("新增任务")
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    onAccepted: widget.addTask()
                }
                SmallButton {
                    objectName: "addTaskButton"
                    text: "+"
                    Accessible.name: qsTr("添加任务")
                    onClicked: widget.addTask()
                }
            }

            ScrollView {
                id: taskView
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                Column {
                    width: taskView.availableWidth
                    spacing: 8

                    Repeater {
                        model: store.tasks

                        Column {
                            id: taskCard
                            required property var modelData
                            width: parent.width
                            spacing: 4

                            function addSubtask() {
                                if (modelData.addSubtask(subtaskInput.text))
                                    subtaskInput.clear()
                            }

                            RowLayout {
                                width: parent.width
                                spacing: 3
                                EditorField {
                                    objectName: "taskTitle" + taskCard.modelData.entryId
                                    text: taskCard.modelData.title
                                    Accessible.name: qsTr("任务名称")
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    onEditingFinished: widget.commit(taskCard.modelData, this)
                                }
                                SmallButton {
                                    objectName: "removeTask" + taskCard.modelData.entryId
                                    text: "×"
                                    destructive: true
                                    Accessible.name: qsTr("删除任务")
                                    onClicked: store.removeTask(taskCard.modelData.entryId)
                                }
                            }

                            Repeater {
                                model: taskCard.modelData.subtasks
                                RowLayout {
                                    id: subtaskRow
                                    required property var modelData
                                    x: 10
                                    width: taskCard.width - 10
                                    spacing: 3
                                    EditorField {
                                        objectName: "subtaskTitle" + subtaskRow.modelData.entryId
                                        text: subtaskRow.modelData.title
                                        Accessible.name: qsTr("子任务名称")
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        onEditingFinished: widget.commit(subtaskRow.modelData, this)
                                    }
                                    SmallButton {
                                        objectName: "removeSubtask" + subtaskRow.modelData.entryId
                                        text: "×"
                                        destructive: true
                                        Accessible.name: qsTr("删除子任务")
                                        onClicked: taskCard.modelData.removeSubtask(subtaskRow.modelData.entryId)
                                    }
                                }
                            }

                            RowLayout {
                                x: 10
                                width: taskCard.width - 10
                                spacing: 3
                                EditorField {
                                    id: subtaskInput
                                    objectName: "newSubtaskInput" + taskCard.modelData.entryId
                                    placeholderText: qsTr("新增子任务")
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    onAccepted: taskCard.addSubtask()
                                }
                                SmallButton {
                                    objectName: "addSubtask" + taskCard.modelData.entryId
                                    text: "+"
                                    Accessible.name: qsTr("添加子任务")
                                    onClicked: taskCard.addSubtask()
                                }
                            }
                        }
                    }

                    Text {
                        visible: store.tasks.length === 0
                        text: qsTr("当天暂无任务")
                        color: "#94a3b8"
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
}
