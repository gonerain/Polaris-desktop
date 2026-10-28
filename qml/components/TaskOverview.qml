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
    property bool showFilters: true
    property int selectedTaskId: 0
    signal taskSelected(var task, string date)
    signal reviewRequested()
    signal addTaskRequested()
    property int draggedTaskId: 0
    property int dropTargetId: 0
    property real dragY: 0
    readonly property bool canReorder: scope === "today" && !search.text.trim()
    readonly property bool escapeBlocked: draggedTaskId !== 0 || (searchVisible && search.activeFocus)
    readonly property var matching: taskStore.allEntries.filter(function(row) {
        const task = row.task
        if (root.scope === "done" ? !task.done : task.done) return false
        if (root.scope === "today" && row.date !== root.taskStore.todayDate) return false
        if (root.scope === "overdue" && !row.overdue) return false
        if (root.scope === "inbox" && row.date !== "") return false
        const query = search.text.trim().toLocaleLowerCase()
        return !query || task.title.toLocaleLowerCase().includes(query) || task.notes.toLocaleLowerCase().includes(query)
            || row.date.includes(query)
            || task.subtasks.some(function(child) { return child.title.toLocaleLowerCase().includes(query) })
    })
    spacing: 12
    TaskRowsModel { id: results; rows: root.matching }
    function openSearch() { searchVisible = true; Qt.callLater(function() { search.forceActiveFocus() }) }
    function updateDrop(y) {
        dragY = y
        const index = list.indexAt(list.width / 2, list.contentY + Math.max(0, Math.min(list.height - 1, y)))
        if (index >= 0 && index < results.count) dropTargetId = results.get(index).identity
    }
    function cancelDrag() { draggedTaskId = 0; dropTargetId = 0 }
    function finishDrag() {
        const source = draggedTaskId, target = dropTargetId
        cancelDrag()
        if (source && target && source !== target) taskStore.reorderToday(source, target)
    }
    Timer {
        interval: 40
        repeat: true
        running: root.draggedTaskId !== 0
        onTriggered: {
            const shift = root.dragY < 28 ? -12 : root.dragY > list.height - 28 ? 12 : 0
            if (shift) {
                list.contentY = Math.max(0, Math.min(Math.max(0, list.contentHeight - list.height), list.contentY + shift))
                root.updateDrop(root.dragY)
            }
        }
    }

    RowLayout {
        visible: root.showFilters
        Layout.fillWidth: true
        Repeater {
            model: [{key: "today", title: qsTr("我的一天")}, {key: "all", title: qsTr("任务库")},
                {key: "overdue", title: qsTr("待重新安排")}, {key: "done", title: qsTr("已完成")}]
            IconButton {
                required property var modelData
                objectName: "todoFilter_" + modelData.key
                text: modelData.title
                textSize: 11
                buttonSize: 32
                selected: root.scope === modelData.key
                onClicked: root.scope = modelData.key
            }
        }
    }
    Rectangle {
        visible: root.scope === "today" && root.taskStore.overdueCount > 0
        Layout.fillWidth: true
        implicitHeight: 42
        radius: 8
        color: "#FFF6EC"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 5
            spacing: 8
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.taskStore.overdueCount + qsTr(" 项旧安排，留待你重新决定")
                color: "#9A7655"
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            IconButton {
                objectName: "reviewOverdue"
                text: qsTr("整理")
                buttonSize: 28
                textSize: 11
                onClicked: root.reviewRequested()
            }
            IconButton {
                objectName: "todayMoveAllOverdue"
                text: qsTr("全部加入今天")
                buttonSize: 28
                textSize: 11
                onClicked: root.taskStore.moveOverdueToToday()
            }
        }
    }
    InlineField {
        id: search
        objectName: "overviewSearch"
        Layout.fillWidth: true
        visible: root.searchVisible
        placeholderText: qsTr("搜索任务、子任务、笔记或日期…")
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
        spacing: 4
        boundsBehavior: Flickable.StopAtBounds
        section.property: root.scope === "today" || root.scope === "inbox" ? "" : "group"
        section.criteria: ViewSection.FullString
        section.delegate: RowLayout {
            required property string section
            width: list.width
            height: 36
            Text {
                Layout.fillWidth: true
                text: section === "overdue" ? qsTr("待重新安排") : section === "inbox" ? qsTr("收集箱") : root.taskStore.dateLabel(section)
                color: Theme.muted
                font.pixelSize: 11
                font.weight: Font.Medium
            }
            IconButton {
                visible: section === "overdue"
                objectName: "overviewMoveAllOverdue"
                text: qsTr("全部加入今天")
                buttonSize: 26
                textSize: 10
                onClicked: root.taskStore.moveOverdueToToday()
            }
        }
        delegate: AbstractButton {
            id: row
            required property var task
            required property string date
            required property bool overdue
            required property int index
            readonly property bool editBoundary: true
            objectName: "taskRow" + task.entryId
            width: list.width
            implicitHeight: 62
            padding: 10
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            Accessible.name: task.title
            ToolTip.visible: row.enabled && row.visible && hovered && titleText.truncated
            ToolTip.text: task.title
            ToolTip.delay: 600
            onClicked: root.taskSelected(task, date)
            background: Rectangle {
                radius: 8
                color: root.selectedTaskId === row.task.entryId || row.visualFocus ? Theme.primarySoft
                    : row.hovered ? "#F1F3F8" : Theme.surface
                border.width: root.dropTargetId === row.task.entryId && root.draggedTaskId !== row.task.entryId ? 2 : 1
                border.color: root.dropTargetId === row.task.entryId ? Theme.primary
                    : root.selectedTaskId === row.task.entryId || row.visualFocus ? "#D4DAFF" : "#EEF0F5"
            }
            contentItem: RowLayout {
                spacing: 8
                Item {
                    visible: root.canReorder
                    Layout.preferredWidth: 14
                    Layout.fillHeight: true
                    Column {
                        anchors.centerIn: parent
                        spacing: 3
                        Repeater { model: 3; Rectangle { width: 2; height: 2; radius: 1; color: Theme.subtle } }
                    }
                    MouseArea {
                        id: reorderHandle
                        objectName: "reorderHandle" + row.task.entryId
                        anchors.fill: parent
                        cursorShape: Qt.SizeVerCursor
                        preventStealing: true
                        acceptedButtons: Qt.LeftButton
                        onPressed: function(mouse) {
                            list.currentIndex = row.index
                            root.draggedTaskId = row.task.entryId
                            root.dropTargetId = row.task.entryId
                            root.updateDrop(mapToItem(list, mouse.x, mouse.y).y)
                        }
                        onPositionChanged: function(mouse) {
                            if (pressed && root.draggedTaskId) root.updateDrop(mapToItem(list, mouse.x, mouse.y).y)
                        }
                        onReleased: function(mouse) {
                            const point = mapToItem(list, mouse.x, mouse.y)
                            if (point.x >= 0 && point.x <= list.width && point.y >= 0 && point.y <= list.height)
                                root.finishDrag()
                            else root.cancelDrag()
                        }
                        onCanceled: root.cancelDrag()
                    }
                }
                TaskCheck {
                    objectName: "overviewToggle" + row.task.entryId
                    checkedState: row.task.done
                    accessibleName: qsTr("完成任务")
                    onToggleRequested: function(value) { row.task.setDone(value) }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 4
                    Text {
                        id: titleText
                        Layout.fillWidth: true
                        text: row.task.title
                        font.pixelSize: 13
                        color: row.task.done ? Theme.muted : Theme.ink
                        font.strikeout: row.task.done
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: {
                            const parts = []
                            if (root.scope !== "today") parts.push(root.taskStore.dateLabel(row.date))
                            if (row.task.time) parts.push(row.task.time)
                            if (row.task.important) parts.push(root.scope === "today" ? qsTr("今日重点") : qsTr("重点"))
                            if (row.task.notes) parts.push(qsTr("有笔记"))
                            if (row.task.subtaskCount) parts.push(qsTr("子任务 ")
                                + row.task.completedSubtaskCount + "/" + row.task.subtaskCount)
                            return parts.join("  ·  ")
                        }
                        visible: !!text
                        color: Theme.muted
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                }
                IconButton {
                    objectName: "importantTask" + row.task.entryId
                    text: row.task.important ? "★" : "☆"
                    textSize: 16
                    buttonSize: 26
                    selected: row.task.important
                    opacity: row.task.important || row.hovered || row.activeFocus || activeFocus ? 1 : 0
                    tooltip: row.task.important ? qsTr("取消重点") : qsTr("标为重点，建议每天选 1–3 项")
                    onClicked: row.task.setImportant(!row.task.important)
                }
                IconButton {
                    objectName: "moveToday" + row.task.entryId
                    visible: !row.task.done && row.date !== root.taskStore.todayDate
                    text: qsTr("加入今天")
                    textSize: 10
                    buttonSize: 28
                    onClicked: root.taskStore.moveTask(row.task.entryId, root.taskStore.todayDate)
                }
                IconButton {
                    id: dateButton
                    objectName: "rescheduleTask" + row.task.entryId
                    text: qsTr("改期")
                    textSize: 10
                    buttonSize: 28
                    opacity: row.hovered || row.activeFocus || root.selectedTaskId === row.task.entryId
                        || activeFocus ? 1 : 0
                    onClicked: datePicker.open()
                    TaskDatePicker {
                        id: datePicker
                        objectName: "taskDatePicker" + row.task.entryId
                        anchorItem: dateButton
                        dateValue: row.date
                        onDateSelected: function(value) { root.taskStore.moveTask(row.task.entryId, value) }
                    }
                }
                Text { text: "›"; font.pixelSize: 18; color: Theme.subtle }
            }
        }
        footer: IconButton {
            width: list.width
            visible: root.scope !== "done"
            text: root.scope === "inbox" || root.scope === "all" ? qsTr("＋ 记到收集箱") : qsTr("＋ 添加到今天")
            textSize: 12
            buttonSize: 38
            onClicked: root.addTaskRequested()
        }
        ScrollBar.vertical: ScrollBar {
            readonly property bool editBoundary: true
            policy: ScrollBar.AsNeeded
        }
        Column {
            anchors.centerIn: parent
            spacing: 10
            visible: list.count === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "✓"
                color: "#CCD2EA"
                font.pixelSize: 34
            }
            Text {
                text: search.text.trim() ? qsTr("没有找到匹配的任务")
                    : root.scope === "overdue" ? qsTr("旧安排已经整理好了")
                    : root.scope === "done" ? qsTr("完成的任务会收在这里")
                    : root.scope === "inbox" ? qsTr("想到什么，先记在这里")
                    : root.scope === "all" ? qsTr("任务库还是空的") : qsTr("今天，先从一件事开始")
                font.pixelSize: 15
                color: Theme.ink
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("从收集箱或任务库挑选，或直接添加到今天")
                color: Theme.muted
                font.pixelSize: 11
                visible: root.scope === "today" && !search.text.trim()
            }
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.escapeBlocked
        onActivated: {
            if (root.draggedTaskId) root.cancelDrag()
            else { search.clear(); root.searchVisible = false }
        }
    }
}
