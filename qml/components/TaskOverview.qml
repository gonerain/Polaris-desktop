pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

ColumnLayout {
    id: root
    required property var taskStore
    readonly property var matching: {
        const query = search.text.trim().toLocaleLowerCase()
        return taskStore.allEntries.filter(function(row) {
            const task = row.task
            if (!showCompleted.checked && task.done) return false
            return !query || task.title.toLocaleLowerCase().includes(query)
                || row.date.includes(query)
                || task.subtasks.some(function(child) { return child.title.toLocaleLowerCase().includes(query) })
        })
    }
    spacing: 14

    RowLayout {
        Layout.fillWidth: true
        InlineField {
            id: search
            objectName: "overviewSearch"
            Layout.fillWidth: true
            placeholderText: qsTr("搜索任务、子任务或日期")
            chip: true
            implicitHeight: 34
            selectByMouse: true
            Accessible.name: placeholderText
        }
        CheckBox {
            id: showCompleted
            objectName: "overviewShowCompleted"
            text: qsTr("含已完成")
            font.pixelSize: 12
            indicator: Rectangle {
                implicitWidth: 16
                implicitHeight: 16
                y: (showCompleted.height - height) / 2
                radius: 4
                color: showCompleted.checked ? Theme.primary : Theme.surface
                border.color: showCompleted.checked ? Theme.primary : Theme.border
                Rectangle {
                    visible: showCompleted.checked
                    x: 3
                    y: 7
                    width: 4
                    height: 1.5
                    color: "white"
                    rotation: 45
                    transformOrigin: Item.Left
                }
                Rectangle {
                    visible: showCompleted.checked
                    x: 6
                    y: 10
                    width: 8
                    height: 1.5
                    color: "white"
                    rotation: -45
                    transformOrigin: Item.Left
                }
            }
            contentItem: Text {
                text: showCompleted.text
                leftPadding: 22
                color: Theme.muted
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
    Text {
        text: root.matching.length + qsTr(" 项")
        color: Theme.muted
        font.pixelSize: 11
    }
    ListView {
        id: list
        objectName: "overviewList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: root.matching
        clip: true
        spacing: 12
        boundsBehavior: Flickable.StopAtBounds
        delegate: ColumnLayout {
            id: row
            required property var modelData
            width: list.width
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                InlineField {
                    id: dateEditor
                    objectName: "taskDate" + row.modelData.task.entryId
                    Layout.preferredWidth: 112
                    text: row.modelData.date
                    font.pixelSize: 11
                    bare: true
                    Accessible.name: qsTr("任务日期，格式 YYYY-MM-DD")
                    onTextEdited: error = false
                    onEditingFinished: {
                        const value = text.trim()
                        if (value === row.modelData.date) return
                        if (!root.taskStore.moveTask(row.modelData.task.entryId, value)) {
                            error = true
                            text = row.modelData.date
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: row.modelData.overdue ? qsTr("逾期") : ""
                    color: Theme.accent
                    font.pixelSize: 10
                }
                IconButton {
                    visible: row.modelData.overdue
                    text: qsTr("今天")
                    buttonSize: 32
                    textSize: 10
                    accessibleName: qsTr("移到今天")
                    onClicked: root.taskStore.moveTask(row.modelData.task.entryId, root.taskStore.todayDate)
                }
            }
            TaskCard {
                Layout.fillWidth: true
                entry: row.modelData.task
                taskStore: root.taskStore
            }
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.border
            }
        }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Text {
            anchors.centerIn: parent
            visible: list.count === 0
            text: search.text.trim() ? qsTr("没有匹配的任务") : qsTr("暂时没有待办，安心安排今天")
            color: Theme.muted
            font.pixelSize: 13
        }
    }
}
