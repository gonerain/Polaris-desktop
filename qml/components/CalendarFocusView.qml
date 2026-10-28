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
    property bool notesOpened: false
    readonly property bool planning: mode === "week" || mode === "month"
    readonly property bool railOnly: width < 1024
    readonly property bool editorOpen: root.Window.window && root.Window.window.editorPopupCount > 0
    readonly property var entries: taskStore.allEntries
    readonly property var selectedRow: entries.find(function (row) {
        return row.task.entryId === root.selectedTaskId;
    }) || null
    readonly property int todayTotal: entries.filter(function (row) {
        return row.date === root.taskStore.todayDate;
    }).length
    readonly property int todayDone: entries.filter(function (row) {
        return row.date === root.taskStore.todayDate && row.task.done;
    }).length
    readonly property int todayImportant: entries.filter(function (row) {
        return row.date === root.taskStore.todayDate && !row.task.done && row.task.important;
    }).length
    readonly property var titles: ({
            todo: qsTr("我的一天"),
            inbox: qsTr("收集箱"),
            library: qsTr("任务库"),
            overdue: qsTr("重新安排"),
            week: qsTr("周计划"),
            month: qsTr("月计划"),
            done: qsTr("已完成")
        })
    readonly property bool escapeBlocked: composer.opened || detailOpen || (!planning && overview.escapeBlocked)
    color: Theme.background
    radius: 12
    border.color: Theme.border
    border.width: 1
    clip: true
    Component.onCompleted: {
        taskStore.goToday();
        selectMode(mode);
    }
    onSelectedRowChanged: {
        if (!selectedRow && selectedTaskId) {
            detailOpen = false;
            selectedTaskId = 0;
        }
    }

    function selectMode(value) {
        detailNotes.commit();
        composer.dismissEditors();
        agenda.closeComposer();
        detailOpen = false;
        selectedTaskId = 0;
        mode = value;
        overview.scope = value === "inbox" ? "inbox" : value === "library" ? "all" : value === "done" ? "done" : value === "overdue" ? "overdue" : "today";
    }
    function beginTask() {
        if (planning && detailOpen)
            agenda.openComposer();
        else {
            const capture = !planning && (mode === "inbox" || mode === "library");
            if (!planning) {
                selectMode(capture ? "inbox" : "todo");
                taskStore.goToday();
            }
            composer.inboxMode = capture;
            composer.open();
        }
    }
    function selectTask(task, date) {
        composer.dismissEditors();
        detailNotes.commit();
        if (selectedTaskId !== task.entryId)
            detailCard.clearSubtaskDraft();
        selectedTaskId = task.entryId;
        detailOpen = true;
        detailCard.expanded = true;
        notesOpened = !!task.notes;
    }
    function beginSearch() {
        selectMode("library");
        overview.openSearch();
    }

    EditDismissArea {
        anchors.fill: parent
    }
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
                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: width
                    contentHeight: navColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    ColumnLayout {
                        id: navColumn
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: [
                                {
                                    key: "todo",
                                    title: qsTr("我的一天"),
                                    short: qsTr("今")
                                },
                                {
                                    key: "inbox",
                                    title: qsTr("收集箱"),
                                    short: qsTr("收")
                                },
                                {
                                    key: "library",
                                    title: qsTr("任务库"),
                                    short: qsTr("库")
                                },
                                {
                                    key: "overdue",
                                    title: qsTr("待重新安排"),
                                    short: qsTr("续")
                                },
                                {
                                    key: "week",
                                    title: qsTr("周计划"),
                                    short: qsTr("周")
                                },
                                {
                                    key: "month",
                                    title: qsTr("月计划"),
                                    short: qsTr("月")
                                },
                                {
                                    key: "done",
                                    title: qsTr("已完成"),
                                    short: qsTr("完")
                                }
                            ]
                            ColumnLayout {
                                id: nav
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                spacing: 8
                                Rectangle {
                                    visible: nav.index === 4 || nav.index === 6
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
                                        color: root.mode === nav.modelData.key ? "#FFFFFF" : navButton.hovered || navButton.visualFocus ? "#E5E9F2" : Theme.clearSurface
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
                                            visible: !root.railOnly && ((nav.modelData.key === "overdue" && root.taskStore.overdueCount > 0) || (nav.modelData.key === "inbox" && root.taskStore.inboxCount > 0))
                                            text: nav.modelData.key === "inbox" ? root.taskStore.inboxCount : root.taskStore.overdueCount
                                            font.pixelSize: 10
                                            color: Theme.muted
                                        }
                                    }
                                }
                            }
                        }
                    }
                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }
                }
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
                        const owner = root.Window.window;
                        if (owner) {
                            owner.moving = active;
                            if (active)
                                owner.startSystemMove();
                        }
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
                        text: root.mode === "todo" ? root.taskStore.todayDate + qsTr("  ·  今天只做主动选择的事") : root.mode === "inbox" ? qsTr("先收集，不必立刻决定哪天做") : root.mode === "library" ? qsTr("所有未完成事项，按需加入今天") : root.mode === "overdue" ? qsTr("旧安排不必挤满今天，重新选择时间就好") : root.mode === "done" ? qsTr("把完成的事收好，把注意力留给现在") : qsTr("按日期规划，查看时再展开当天安排")
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
                    text: root.width < 700 ? "+" : root.planning ? qsTr("＋ 安排任务") : root.mode === "inbox" || root.mode === "library" ? qsTr("＋ 随手记下") : qsTr("＋ 添加到今天")
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
                    text: root.mode === "todo" ? (root.todayTotal - root.todayDone) + qsTr(" 项待办 · 重点 ") + root.todayImportant + qsTr(" 项") : ""
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
                    id: reviewButton
                    objectName: "openDayReview"
                    visible: root.mode === "todo"
                    text: qsTr("整理今天")
                    textSize: 11
                    buttonSize: 28
                    onClicked: dayReview.open()
                    DayReviewPopup {
                        id: dayReview
                        anchorItem: reviewButton
                        taskStore: root.taskStore
                    }
                }
                IconButton {
                    visible: root.planning
                    text: qsTr("当天安排")
                    textSize: 11
                    buttonSize: 28
                    selected: root.detailOpen
                    onClicked: {
                        composer.dismissEditors();
                        root.detailOpen = !root.detailOpen;
                    }
                }
            }
            Text {
                visible: composer.opened
                text: composer.inboxMode ? qsTr("记录到收集箱 · 暂不安排日期") : qsTr("添加到 ") + root.taskStore.dateLabel(root.taskStore.selectedDate)
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
                    onTaskSelected: function (task, date) {
                        root.selectTask(task, date);
                    }
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
                        onDayActivated: function (date, addTask) {
                            composer.dismissEditors();
                            root.taskStore.selectDate(date);
                            root.detailOpen = true;
                            if (addTask)
                                Qt.callLater(function () {
                                    agenda.openComposer();
                                });
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
                                    onDateSelected: function (value) {
                                        if (root.selectedRow)
                                            root.taskStore.moveTask(root.selectedTaskId, value);
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                IconButton {
                                    objectName: "detailImportant"
                                    text: root.selectedRow && root.selectedRow.task.important ? qsTr("★ 已设为重点") : qsTr("☆ 设为重点")
                                    selected: root.selectedRow && root.selectedRow.task.important
                                    textSize: 11
                                    buttonSize: 28
                                    onClicked: if (root.selectedRow)
                                        root.selectedRow.task.setImportant(!root.selectedRow.task.important)
                                }
                                Item {
                                    Layout.fillWidth: true
                                }
                                IconButton {
                                    visible: root.selectedRow && !!root.selectedRow.date
                                    text: qsTr("放回收集箱")
                                    textSize: 10
                                    buttonSize: 28
                                    onClicked: root.taskStore.moveTask(root.selectedTaskId, "")
                                }
                            }
                            Flickable {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                contentHeight: detailBody.implicitHeight
                                boundsBehavior: Flickable.StopAtBounds
                                ColumnLayout {
                                    id: detailBody
                                    width: parent.width
                                    spacing: 10
                                    TaskCard {
                                        id: detailCard
                                        objectName: "detailTaskCard"
                                        Layout.fillWidth: true
                                        entry: root.selectedRow ? root.selectedRow.task : null
                                        taskStore: root.taskStore
                                    }
                                    IconButton {
                                        objectName: "toggleTaskNotes"
                                        text: root.notesOpened ? qsTr("下一步与笔记 · 收起") : qsTr("＋ 下一步与笔记")
                                        textSize: 11
                                        buttonSize: 30
                                        onClicked: root.notesOpened = !root.notesOpened
                                    }
                                    TaskNotes {
                                        id: detailNotes
                                        Layout.fillWidth: true
                                        visible: root.notesOpened
                                        entry: root.selectedRow ? root.selectedRow.task : null
                                    }
                                }
                                ScrollBar.vertical: ScrollBar {
                                    policy: ScrollBar.AsNeeded
                                }
                            }
                            IconButton {
                                Layout.fillWidth: true
                                text: root.selectedRow && root.selectedRow.task.done ? qsTr("标为未完成") : qsTr("完成任务")
                                filled: true
                                buttonSize: 34
                                textSize: 12
                                onClicked: if (root.selectedRow)
                                    root.selectedRow.task.setDone(!root.selectedRow.task.done)
                            }
                        }
                    }
                }
            }
            StoreStatus {
                Layout.fillWidth: true
                taskStore: root.taskStore
            }
        }
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: root.visible && !root.editorOpen && !(root.planning && root.detailOpen)
        onActivated: root.beginTask()
    }
    Shortcut {
        sequence: "Ctrl+F"
        enabled: root.visible && !root.editorOpen
        onActivated: root.beginSearch()
    }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.detailOpen && !(root.planning && agenda.composerOpen) && !composer.opened && !overview.escapeBlocked && !root.editorOpen
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
        onActivated: {
            root.selectMode("todo");
            root.taskStore.goToday();
        }
    }
}
