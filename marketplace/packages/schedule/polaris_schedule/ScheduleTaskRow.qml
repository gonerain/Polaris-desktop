import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: row
    required property var host
    readonly property var colors: host.appearance
    required property var task
    required property int rowIndex
    property string prefix: ''
    property bool draggable: false
    height: 48
    radius: 8
    color: mouse.containsMouse ? colors.hover : colors.surface
    border.color: activeFocus ? colors.accent : colors.border
    border.width: 1
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(event) { row.forceActiveFocus(); if (event.button === Qt.RightButton) actions.popup(); else row.host.openTask(row.task) }
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 3; anchors.rightMargin: 3
        spacing: 2
        ScheduleButton { appearance: row.colors;
            objectName: row.prefix + 'completeTask_' + row.rowIndex
            text: row.task.done ? '✓' : '○'; selected: row.task.done
            Accessible.name: row.task.done ? '标为未完成' : '完成任务'
            onClicked: row.host.call('update', {identity: row.task.id, done: !row.task.done})
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 1
            Text { Layout.fillWidth: true; text: row.task.title; textFormat: Text.PlainText; font.pixelSize: 12; font.strikeout: row.task.done; color: row.task.done ? colors.muted : colors.text; elide: Text.ElideRight }
            Text {
                Layout.fillWidth: true
                text: [row.task.time || '', row.host.section !== '我的一天' || row.draggable ? (row.task.date || '收集箱') : '', row.task.subtasks.length ? row.task.subtasks.filter(function(s) {return s.done}).length + '/' + row.task.subtasks.length : ''].filter(function(s) {return s.length > 0}).join(' · ')
                visible: text.length > 0; textFormat: Text.PlainText; font.pixelSize: 10
                color: row.task.date && row.task.date < row.host.todayDate && !row.task.done ? colors.warning : colors.muted
                elide: Text.ElideRight
            }
        }
        ScheduleButton { appearance: row.colors;
            visible: !row.draggable
            objectName: row.prefix + 'importantTask_' + row.rowIndex
            text: row.task.important ? '★' : '☆'; selected: row.task.important
            Accessible.name: '切换重点'
            onClicked: row.host.call('update', {identity: row.task.id, important: !row.task.important})
        }
        ScheduleButton { appearance: row.colors;
            objectName: row.prefix + 'taskActions_' + row.rowIndex
            text: '⋯'; Accessible.name: '任务操作'
            onClicked: actions.popup()
        }
        Item {
            visible: row.draggable
            Layout.preferredWidth: 20; Layout.fillHeight: true
            Text { anchors.centerIn: parent; text: '⠿'; color: colors.muted; font.pixelSize: 18 }
            MouseArea {
                id: dragHandle
                objectName: row.prefix + 'dragTask_' + row.rowIndex
                anchors.fill: parent
                cursorShape: Qt.OpenHandCursor
                drag.target: dragPreview
                onPressed: { var point = mapToItem(row.host, 0, 0); dragPreview.x = point.x; dragPreview.y = point.y }
                onReleased: dragPreview.Drag.drop()
                onCanceled: dragPreview.Drag.cancel()
            }
        }
    }
    Rectangle {
        id: dragPreview
        parent: row.host
        z: 1000; width: 150; height: 34; radius: 7
        visible: dragHandle.drag.active
        color: colors.selected; border.color: colors.accent
        property var task: row.task
        Drag.active: dragHandle.drag.active
        Drag.source: dragPreview
        Drag.keys: ['polaris-schedule-task']
        Drag.hotSpot.x: 8; Drag.hotSpot.y: 16
        Text { anchors.fill: parent; anchors.margins: 6; text: row.task.title; textFormat: Text.PlainText; elide: Text.ElideRight; color: colors.text }
    }
    Menu {
        palette.window: colors.raised; palette.text: colors.text; palette.buttonText: colors.text; palette.highlight: colors.selected; palette.highlightedText: colors.text
        id: actions
        MenuItem { objectName: row.prefix + 'planToday_' + row.rowIndex; text: '安排到今天'; onTriggered: { var day = row.host.currentDay(0); if (day) row.host.planTask(row.task, day) } }
        MenuItem { objectName: row.prefix + 'planTomorrow_' + row.rowIndex; text: '安排到明天'; onTriggered: { var day = row.host.currentDay(1); if (day) row.host.planTask(row.task, day) } }
        MenuItem { text: '移回收集箱'; onTriggered: row.host.planTask(row.task, null) }
        MenuItem { text: '详情 / 选择日期…'; onTriggered: row.host.openTask(row.task) }
        MenuSeparator { }
        MenuItem { objectName: row.prefix + 'moveUp_' + row.rowIndex; text: '上移'; onTriggered: row.host.reorderTask(row.task, -1) }
        MenuItem { text: '下移'; onTriggered: row.host.reorderTask(row.task, 1) }
        MenuSeparator { }
        MenuItem { text: '删除'; onTriggered: row.host.call('delete', {identity: row.task.id}) }
    }
}
