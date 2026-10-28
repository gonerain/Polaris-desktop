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
    property int selectedTaskId: 0
    readonly property bool planning: mode === "week" || mode === "month"
    readonly property bool railOnly: width < 1024
    readonly property bool editorOpen: root.Window.window && root.Window.window.editorPopupCount > 0
    readonly property var entries: taskStore.allEntries
    readonly property var selectedRow: entries.find(function(row) {
        return row.task.entryId === root.selectedTaskId
    }) || null
    readonly property int todayTotal: entries.filter(function(row) {
        return row.date === root.taskStore.todayDate
    }).length
    readonly property int todayDone: entries.filter(function(row) {
        return row.date === root.taskStore.todayDate && row.task.done
    }).length
    readonly property var titles: ({todo: qsTr("我的一天"), library: qsTr("任务库"),
        overdue: qsTr("重新安排"), week: qsTr("周计划"), month: qsTr("月计划"), done: qsTr("已完成")})
    readonly property bool escapeBlocked: composer.opened || detailOpen
        || (!planning && overview.escapeBlocked)
    color: Theme.background
    radius: 12
    border.color: Theme.border
    border.width: 1
    clip: true
    Component.onCompleted: taskStore.goToday()
    onSelectedRowChanged: {
        if (!selectedRow && selectedTaskId) { detailOpen = false; selectedTaskId = 0 }
    }

    function selectMode(value) {
        composer.dismissEditors()
        agenda.closeComposer()
        detailOpen = false
        selectedTaskId = 0
        mode = value
        overview.scope = value === "library" ? "all" : value === "done" ? "done"
            : value === "overdue" ? "overdue" : "today"
    }
    function beginTask() {
        if (planning && detailOpen) agenda.openComposer()
        else {
            if (!planning) { selectMode("todo"); taskStore.goToday() }
            composer.open()
        }
    }
    function selectTask(task, date) {
        composer.dismissEditors()
        if (selectedTaskId !== task.entryId) detailCard.clearSubtaskDraft()
        selectedTaskId = task.entryId
        detailOpen = true
        detailCard.expanded = true
    }
    function beginSearch() { selectMode("library"); overview.openSearch() }

    EditDismissArea { anchors.fill: parent }
    RowLayout {
        anchors.fill: parent
        anchors.margins: 1
        spacing: 0
        Rectangle {
            Layout.preferredWidth: root.railOnly ? 58 : 160
            Layout.fillHeight: true
            color: "#EFF1F5"
            radius: 11
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: root.railOnly ? 7 : 12
                spacing: 6
                Text {
                    Layout.fillWidth: true
                    Layout.topMargin: 15
                    Layout.bottomMargin: 23
                    text: root.railOnly ? "P" : "Polaris"
                    horizontalAlignment: root.railOnly ? Text.AlignHCenter : Text.AlignLeft
                    color: Theme.ink
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                }
                Repeater {
                    model: [{key: "todo", title: qsTr("我的一天"), short: qsTr("今")},
                        {key: "library", title: qsTr("任务库"), short: qsTr("库")},
                        {key: "overdue", title: qsTr("待重新安排"), short: qsTr("续")},
                        {key: "week", title: qsTr("周计划"), short: qsTr("周")},
                        {key: "month", title: qsTr("月计划"), short: qsTr("月")},
                        {key: "done", title: qsTr("已完成"), short: qsTr("完")}]
                    ColumnLayout {
                        id: nav
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 8
                        Rectangle {
                            visible: nav.index === 3 || nav.index === 5
                            Layout.fillWidth: true
                            Layout.topMargin: 9
                            Layout.bottomMargin: 5
                            height: 1
                            color: "#E0E4EC"
                        }
                        Button {
                            id: navButton
                            objectName: "focusMode_" + nav.modelData.key
                            Layout.fillWidth: true
                            implicitHeight: 40
                            padding: root.railOnly ? 4 : 10
                            hoverEnabled: true
                            focusPolicy: Qt.StrongFocus
                            text: nav.modelData.title
                            ToolTip.visible: hovered && root.railOnly
                            ToolTip.text: text
                            onClicked: root.selectMode(nav.modelData.key)
                            background: Rectangle {
                                radius: 8
                                color: root.mode === nav.modelData.key ? "#FFFFFF"
                                    : navButton.hovered || navButton.visualFocus ? "#E5E9F2" : Theme.clearSurface
                            }
                            contentItem: RowLayout {
                                spacing: 6
                                Text {
                                    Layout.fillWidth: true
                                    text: root.railOnly ? nav.modelData.short : nav.modelData.title
                                    horizontalAlignment: root.railOnly ? Text.AlignHCenter : Text.AlignLeft
                                    color: root.mode === nav.modelData.key ? Theme.primary : "#677287"
                                    font.pixelSize: 12
                                    font.weight: root.mode === nav.modelData.key ? Font.DemiBold : Font.Normal
                                }
                                Text {
                                    visible: !root.railOnly && nav.modelData.key === "overdue" && root.taskStore.overdueCount > 0
                                    text: root.taskStore.overdueCount
                                    font.pixelSize: 10
                                    color: Theme.muted
                                }
                            }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
                IconButton {
                    objectName: "focusBackButton"
                    Layout.fillWidth: true
                    text: root.railOnly ? "←" : qsTr("← 返回画布")
                    textSize: 11
                    buttonSize: 34
                    tooltip: qsTr("返回画布 · Esc")
                    onClicked: root.presentation.close()
                }
            }
        }
        ColumnLayout {
            id: workspace
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: root.width > 900 ? 22 : 14
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                DragHandler {
                    target: null
                    acceptedButtons: Qt.LeftButton
                    onActiveChanged: {
                        const owner = root.Window.window
                        if (owner) { owner.moving = active; if (active) owner.startSystemMove() }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 7
                    Text {
                        text: root.titles[root.mode]
                        color: Theme.ink
                        font.pixelSize: 23
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.mode === "todo" ? root.taskStore.todayDate + qsTr("  ·  今天只做主动选择的事")
                            : root.mode === "library" ? qsTr("所有未完成事项，按需加入今天")
                            : root.mode === "overdue" ? qsTr("旧安排不必挤满今天，重新选择时间就好")
                            : root.mode === "done" ? qsTr("把完成的事收好，把注意力留给现在")
                            : qsTr("按日期规划，查看时再展开当天安排")
                        color: Theme.muted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }
                IconButton {
                    objectName: "workbenchSearch"
                    text: qsTr("搜索")
                    textSize: 11
                    buttonSize: 34
                    onClicked: root.beginSearch()
                }
                IconButton {
                    objectName: "focusAddTask"
                    text: root.width < 700 ? "+" : root.planning ? qsTr("＋ 安排任务") : qsTr("＋ 添加到今天")
                    filled: true
                    buttonSize: 34
                    textSize: 11
                    onClicked: root.beginTask()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.mode === "todo" || root.planning
                Text {
                    Layout.fillWidth: true
                    text: root.mode === "todo" ? (root.todayTotal - root.todayDone) + qsTr(" 项待办") : ""
                    color: Theme.muted
                    font.pixelSize: 11
                }
                Rectangle {
                    visible: root.mode === "todo" && root.todayTotal > 0
                    width: 70
                    height: 4
                    radius: 2
                    color: "#E3E7F0"
                    Rectangle {
                        width: parent.width * root.todayDone / Math.max(1, root.todayTotal)
                        height: parent.height
                        radius: 2
                        color: Theme.primary
                    }
                }
                Text {
                    visible: root.mode === "todo" && root.todayTotal > 0
                    text: root.todayDone + "/" + root.todayTotal + qsTr(" 已完成")
                    color: Theme.muted
                    font.pixelSize: 10
                }
                IconButton {
                    visible: root.planning
                    text: qsTr("当天安排")
                    textSize: 11
                    buttonSize: 28
                    selected: root.detailOpen
                    onClicked: { composer.dismissEditors(); root.detailOpen = !root.detailOpen }
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
            GridLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                columns: workspace.width >= 850 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 12
                TaskOverview {
                    id: overview
                    objectName: "taskOverview"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 0
                    visible: !root.planning
                    showFilters: false
                    taskStore: root.taskStore
                    selectedTaskId: root.selectedTaskId
                    onTaskSelected: function(task, date) { root.selectTask(task, date) }
                    onReviewRequested: root.selectMode("overdue")
                    onAddTaskRequested: root.beginTask()
                }
                Loader {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 0
                    visible: root.planning
                    active: root.planning
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
                    visible: root.detailOpen && (root.planning || !!root.selectedRow)
                    Layout.preferredWidth: 340
                    Layout.fillWidth: workspace.width < 850
                    Layout.fillHeight: workspace.width >= 850
                    Layout.preferredHeight: workspace.width < 850 ? Math.min(300, root.height * 0.44) : -1
                    radius: 10
                    color: Theme.surface
                    border.color: Theme.border
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: root.planning ? qsTr("当天安排") : qsTr("任务详情")
                                color: Theme.muted
                                font.pixelSize: 11
                            }
                            IconButton {
                                objectName: "closeTaskDetails"
                                text: "×"
                                buttonSize: 24
                                onClicked: root.detailOpen = false
                            }
                        }
                        AgendaPanel {
                            id: agenda
                            objectName: "focusAgenda"
                            visible: root.planning
                            showCalendarButton: false
                            taskStore: root.taskStore
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                        }
                        ColumnLayout {
                            visible: !root.planning && !!root.selectedRow
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 12
                            IconButton {
                                id: detailDate
                                objectName: "detailDateButton"
                                text: root.selectedRow ? qsTr("安排日期 · ") + root.taskStore.dateLabel(root.selectedRow.date) : ""
                                textSize: 11
                                buttonSize: 30
                                selected: true
                                onClicked: detailDatePicker.open()
                                TaskDatePicker {
                                    id: detailDatePicker
                                    objectName: "detailDatePicker"
                                    anchorItem: detailDate
                                    dateValue: root.selectedRow ? root.selectedRow.date : ""
                                    onDateSelected: function(value) {
                                        if (root.selectedRow) root.taskStore.moveTask(root.selectedTaskId, value)
                                    }
                                }
                            }
                            Flickable {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                contentHeight: detailCard.implicitHeight
                                boundsBehavior: Flickable.StopAtBounds
                                TaskCard {
                                    id: detailCard
                                    objectName: "detailTaskCard"
                                    width: parent.width
                                    height: implicitHeight
                                    entry: root.selectedRow ? root.selectedRow.task : null
                                    taskStore: root.taskStore
                                }
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            }
                            IconButton {
                                Layout.fillWidth: true
                                text: root.selectedRow && root.selectedRow.task.done ? qsTr("标为未完成") : qsTr("完成任务")
                                filled: true
                                buttonSize: 34
                                textSize: 12
                                onClicked: if (root.selectedRow) root.selectedRow.task.setDone(!root.selectedRow.task.done)
                            }
                        }
                    }
                }
            }
            StoreStatus { Layout.fillWidth: true; taskStore: root.taskStore }
        }
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: root.visible && !root.editorOpen && !(root.planning && root.detailOpen)
        onActivated: root.beginTask()
    }
    Shortcut { sequence: "Ctrl+F"; enabled: root.visible && !root.editorOpen; onActivated: root.beginSearch() }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.detailOpen && !(root.planning && agenda.composerOpen)
            && !composer.opened && !overview.escapeBlocked
            && !root.editorOpen
        onActivated: root.detailOpen = false
    }
    Shortcut {
        sequence: "Alt+Left"
        enabled: root.visible && root.planning && !root.detailOpen && !root.editorOpen
        onActivated: root.mode === "week" ? root.taskStore.changeDay(-7) : root.taskStore.changeMonth(-1)
    }
    Shortcut {
        sequence: "Alt+Right"
        enabled: root.visible && root.planning && !root.detailOpen && !root.editorOpen
        onActivated: root.mode === "week" ? root.taskStore.changeDay(7) : root.taskStore.changeMonth(1)
    }
    Shortcut {
        sequence: "Ctrl+T"
        enabled: root.visible && !root.detailOpen && !root.editorOpen
        onActivated: { root.selectMode("todo"); root.taskStore.goToday() }
    }
}
