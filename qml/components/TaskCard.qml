pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: card
    objectName: "taskCard" + (entry ? entry.entryId : "")

    property var entry
    property var taskStore
    property bool expanded: false
    property bool animateEntrance: false
    readonly property bool completed: entry ? entry.done : false

    implicitHeight: content.implicitHeight + 16
    radius: 9
    clip: true
    color: cardHover.hovered ? "#F8FAFF" : Theme.clearSurface
    opacity: animateEntrance ? 0 : 1
    scale: 1

    Behavior on color {
        ColorAnimation { duration: Theme.fast }
    }

    HoverHandler {
        id: cardHover
    }

    ParallelAnimation {
        id: entrance

        NumberAnimation {
            target: card
            property: "opacity"
            from: 0
            to: 1
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }

        NumberAnimation {
            target: card
            property: "scale"
            from: 0.98
            to: 1
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }
    }

    Component.onCompleted: {
        if (card.entry && card.animateEntrance)
            entrance.start()
    }

    function commitTitle(field: TextField) {
        if (!card.entry)
            return
        card.entry.rename(field.text)
        field.text = Qt.binding(function() { return card.entry.title })
    }

    function commitSubtaskTitle(subtask, field: TextField) {
        if (!subtask)
            return
        subtask.rename(field.text)
        field.text = Qt.binding(function() { return subtask.title })
    }

    function addSubtask() {
        if (!card.entry)
            return
        if (card.entry.addSubtask(subtaskInput.text))
            subtaskInput.clear()
        subtaskInput.forceActiveFocus()
    }

    function dismissEditors() {
        card.expanded = false
    }

    function beginSubtask() {
        card.expanded = true
        Qt.callLater(function() { subtaskInput.forceActiveFocus() })
    }

    ColumnLayout {
        id: content

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            spacing: 7

            TaskCheck {
                objectName: "toggleTask" + (card.entry ? card.entry.entryId : "")
                checkedState: card.completed
                accessibleName: qsTr("完成任务")
                onToggleRequested: function(next) {
                    if (card.entry)
                        card.entry.setDone(next)
                }
            }

            TimeField {
                id: timeField
                objectName: "taskTime" + (card.entry ? card.entry.entryId : "")
                Layout.preferredWidth: 48
                Layout.minimumWidth: 44
                Layout.maximumWidth: 52
                text: card.entry ? card.entry.time : ""
                placeholderText: qsTr("全天")
                bare: true
                horizontalAlignment: TextInput.AlignHCenter
                font.pixelSize: 10
                color: card.completed ? Theme.subtle : Theme.muted
                onTimeSelected: function(value) {
                    if (card.entry) card.entry.setTime(value)
                }
            }

            InlineField {
                id: titleField
                objectName: "taskTitle" + (card.entry ? card.entry.entryId : "")
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: card.entry ? card.entry.title : ""
                placeholderText: qsTr("任务名称")
                bare: true
                font.pixelSize: 13
                font.strikeout: card.completed
                color: card.completed ? Theme.subtle : Theme.ink
                onEditingFinished: card.commitTitle(this)
            }

            IconButton {
                objectName: "addSubtaskLink" + (card.entry ? card.entry.entryId : "")
                text: "+"
                textSize: 14
                buttonSize: 22
                visible: !!card.entry && card.entry.subtaskCount === 0 && !card.expanded
                opacity: cardHover.hovered || titleField.activeFocus || card.expanded || activeFocus ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                accessibleName: qsTr("添加子任务")
                tooltip: qsTr("添加子任务")
                onClicked: card.beginSubtask()
            }

            IconButton {
                objectName: "removeTask" + (card.entry ? card.entry.entryId : "")
                text: "×"
                textSize: 14
                buttonSize: 22
                destructive: true
                opacity: cardHover.hovered || titleField.activeFocus || card.expanded || activeFocus ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                accessibleName: qsTr("删除任务")
                tooltip: qsTr("删除任务")
                onClicked: {
                    if (card.entry && card.taskStore)
                        card.taskStore.removeTask(card.entry.entryId)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 27
            spacing: 4
            visible: !!card.entry && card.entry.subtaskCount > 0

            Text {
                Layout.fillWidth: true
                text: card.entry
                    ? card.entry.completedSubtaskCount + "/" + card.entry.subtaskCount + qsTr(" 子任务")
                    : ""
                color: card.entry && card.entry.completedSubtaskCount === card.entry.subtaskCount
                    ? Theme.success
                    : Theme.muted
                font.pixelSize: 10
                elide: Text.ElideRight

                Behavior on color {
                    ColorAnimation { duration: Theme.fast }
                }
            }

            ChevronButton {
                objectName: "toggleSubtasks" + (card.entry ? card.entry.entryId : "")
                up: card.expanded
                textSize: 12
                buttonSize: 22
                accessibleName: card.expanded ? qsTr("收起子任务") : qsTr("展开子任务")
                tooltip: accessibleName
                onClicked: card.expanded = !card.expanded
            }
        }

        Item {
            id: subtaskWrapper
            readonly property bool editBoundary: true
            objectName: "subtaskWrapper" + (card.entry ? card.entry.entryId : "")

            property real targetHeight: card.expanded ? subtaskColumn.implicitHeight : 0

            Layout.fillWidth: true
            Layout.leftMargin: 27
            Layout.preferredHeight: targetHeight
            visible: card.expanded || targetHeight > 0
            opacity: card.expanded ? 1 : 0
            clip: true
            enabled: card.expanded

            Behavior on targetHeight {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Behavior on opacity {
                NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic }
            }

            Column {
                id: subtaskColumn
                width: parent.width
                spacing: 3

                Repeater {
                    model: card.entry ? card.entry.subtasks : []

                    RowLayout {
                        id: subtaskRow
                        required property var modelData
                        width: subtaskColumn.width
                        spacing: 4

                        TaskCheck {
                            objectName: "toggleSubtask" + subtaskRow.modelData.entryId
                            checkedState: subtaskRow.modelData.done
                            accessibleName: qsTr("完成子任务")
                            onToggleRequested: function(next) {
                                subtaskRow.modelData.setDone(next)
                            }
                        }

                        InlineField {
                            objectName: "subtaskTitle" + subtaskRow.modelData.entryId
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: subtaskRow.modelData.title
                            placeholderText: qsTr("子任务名称")
                            bare: true
                            font.pixelSize: 11
                            font.strikeout: subtaskRow.modelData.done
                            color: subtaskRow.modelData.done ? Theme.subtle : Theme.ink
                            onEditingFinished: card.commitSubtaskTitle(subtaskRow.modelData, this)
                        }

                        IconButton {
                            objectName: "removeSubtask" + subtaskRow.modelData.entryId
                            text: "×"
                            textSize: 13
                            buttonSize: 21
                            destructive: true
                            accessibleName: qsTr("删除子任务")
                            tooltip: qsTr("删除子任务")
                            onClicked: card.entry.removeSubtask(subtaskRow.modelData.entryId)
                        }
                    }
                }

                RowLayout {
                    width: subtaskColumn.width
                    spacing: 4

                    Item {
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 1
                    }

                    InlineField {
                        id: subtaskInput
                        objectName: "newSubtaskInput" + (card.entry ? card.entry.entryId : "")
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        placeholderText: qsTr("新增子任务")
                        bare: true
                        font.pixelSize: 11
                        onAccepted: card.addSubtask()
                    }

                    IconButton {
                        objectName: "addSubtask" + (card.entry ? card.entry.entryId : "")
                        text: "+"
                        textSize: 14
                        buttonSize: 22
                        accessibleName: qsTr("添加子任务")
                        tooltip: qsTr("添加子任务")
                        onClicked: card.addSubtask()
                    }
                }
            }
        }
    }
}
