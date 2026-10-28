pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

ColumnLayout {
    id: root
    required property var taskStore
    property string scope: "today"
    property bool searchVisible: false
    readonly property bool escapeBlocked: searchVisible && search.activeFocus
    readonly property var entries: taskStore.allEntries
    readonly property var matching: entries.filter(function(row) {
        const task = row.task
        if (root.scope === "done" ? !task.done : task.done) return false
        if (root.scope === "today" && row.date > root.taskStore.todayDate) return false
        if (root.scope === "overdue" && !row.overdue) return false
        const query = search.text.trim().toLocaleLowerCase()
        return !query || task.title.toLocaleLowerCase().includes(query) || row.date.includes(query)
            || task.subtasks.some(function(child) { return child.title.toLocaleLowerCase().includes(query) })
    })
    spacing: 14
    TaskRowsModel { id: results; rows: root.matching }
    function openSearch() { searchVisible = true; Qt.callLater(function() { search.forceActiveFocus() }) }

    RowLayout {
        Layout.fillWidth: true
        spacing: 5
        Repeater {
            model: [{key: "today", title: qsTr("今天")}, {key: "all", title: qsTr("全部待办")},
                {key: "overdue", title: qsTr("过期")}, {key: "done", title: qsTr("已完成")}]
            IconButton {
                required property var modelData
                objectName: "todoFilter_" + modelData.key
                text: modelData.title
                textSize: 12
                buttonSize: 32
                selected: root.scope === modelData.key
                onClicked: root.scope = modelData.key
            }
        }
        Item { Layout.fillWidth: true }
        Text {
            text: root.matching.length + qsTr(" 项")
            color: Theme.muted
            font.pixelSize: 11
        }
        IconButton {
            objectName: "toggleTodoSearch"
            text: qsTr("搜索")
            textSize: 11
            buttonSize: 30
            selected: root.searchVisible
            onClicked: {
                if (root.searchVisible) { search.clear(); root.searchVisible = false }
                else root.openSearch()
            }
        }
    }
    InlineField {
        id: search
        objectName: "overviewSearch"
        Layout.fillWidth: true
        visible: root.searchVisible
        placeholderText: qsTr("搜索任务、子任务或日期…")
        chip: true
        implicitHeight: 36
        Accessible.name: placeholderText
    }
    ListView {
        id: list
        objectName: "overviewList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: results
        clip: true
        spacing: 7
        boundsBehavior: Flickable.StopAtBounds
        section.property: "group"
        section.criteria: ViewSection.FullString
        section.delegate: RowLayout {
            required property string section
            width: list.width
            height: 42
            Text {
                Layout.fillWidth: true
                text: section === "overdue" ? qsTr("待重新安排") : root.taskStore.dateLabel(section)
                color: section === "overdue" ? "#B76742" : Theme.ink
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
            IconButton {
                visible: section === "overdue"
                objectName: "overviewMoveAllOverdue"
                text: qsTr("全部移到今天 →")
                buttonSize: 28
                textSize: 11
                onClicked: root.taskStore.moveOverdueToToday()
            }
        }
        delegate: Rectangle {
            id: row
            required property var task
            required property string date
            required property bool overdue
            width: list.width
            implicitHeight: body.implicitHeight + 16
            radius: 12
            color: Theme.surface
            border.color: row.overdue ? "#F2E1D7" : Theme.border
            ColumnLayout {
                id: body
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: 8
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 4
                    Text {
                        Layout.fillWidth: true
                        text: row.overdue ? qsTr("原定 ") + root.taskStore.dateLabel(row.date)
                            : root.taskStore.dateLabel(row.date)
                        color: row.overdue ? "#B76742" : Theme.muted
                        font.pixelSize: 10
                    }
                    IconButton {
                        objectName: "moveToday" + row.task.entryId
                        visible: !row.task.done && row.date !== root.taskStore.todayDate
                        text: row.overdue ? qsTr("移到今天") : qsTr("安排到今天")
                        textSize: 10
                        buttonSize: 26
                        selected: row.overdue
                        onClicked: root.taskStore.moveTask(row.task.entryId, root.taskStore.todayDate)
                    }
                    IconButton {
                        id: dateButton
                        objectName: "rescheduleTask" + row.task.entryId
                        text: qsTr("改期")
                        textSize: 10
                        buttonSize: 26
                        onClicked: datePicker.open()
                        TaskDatePicker {
                            id: datePicker
                            objectName: "taskDatePicker" + row.task.entryId
                            anchorItem: dateButton
                            dateValue: row.date
                            onDateSelected: function(value) { root.taskStore.moveTask(row.task.entryId, value) }
                        }
                    }
                }
                TaskCard {
                    Layout.fillWidth: true
                    entry: row.task
                    taskStore: root.taskStore
                }
            }
        }
        ScrollBar.vertical: ScrollBar {
            readonly property bool editBoundary: true
            policy: ScrollBar.AsNeeded
        }
        Column {
            anchors.centerIn: parent
            spacing: 12
            visible: list.count === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "✓"
                color: "#CCD2EA"
                font.pixelSize: 40
            }
            Text {
                text: search.text.trim() ? qsTr("没有找到匹配的任务")
                    : root.scope === "overdue" ? qsTr("没有过期待办，安排得很好")
                    : root.scope === "done" ? qsTr("完成的任务会收在这里") : qsTr("今天轻装上阵")
                font.pixelSize: 16
                font.weight: Font.Medium
                color: Theme.ink
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("用右上角「添加待办」开始安排")
                font.pixelSize: 11
                color: Theme.muted
                visible: !search.text.trim() && root.scope !== "overdue" && root.scope !== "done"
            }
        }
    }
    Shortcut {
        sequence: "Ctrl+F"
        enabled: root.visible && root.enabled
        onActivated: root.openSearch()
    }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.escapeBlocked
        onActivated: { search.clear(); root.searchVisible = false }
    }
}
