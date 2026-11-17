import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: row
    required property var host
    required property var task
    property bool draggable: false
    readonly property var colors: host.colors
    implicitHeight: body.implicitHeight+18
    radius: 8
    color: mouse.containsMouse?colors.hover:colors.surface
    opacity: task.done ? 0.65 : 1
    RowLayout {
        id: body
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 9 }
        spacing: 8
        AbstractButton {
            objectName: 'complete_'+row.task.id
            implicitWidth: 19; implicitHeight: 22
            contentItem: Rectangle { width: 17; height: 17; radius: 5; color: row.task.done?row.colors.accent:'transparent'; border.color: row.task.done?row.colors.accent:row.colors.muted; Text { anchors.centerIn: parent; text: '✓'; visible: row.task.done; font.pixelSize: 11; color: row.colors.onAccent } }
            onClicked: row.host.write('update',{identity:row.task.id,done:!row.task.done})
            Accessible.name: row.task.done?'标记未完成':'完成任务'
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 3
            Text { Layout.fillWidth: true; text: row.task.title; textFormat: Text.PlainText; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 12; font.strikeout: row.task.done; color: row.colors.text }
            Text { Layout.fillWidth: true; visible: !!row.task.date||!!row.task.notes||(row.task.subtasks||[]).length>0; text: (row.task.date?(row.task.date===row.host.today?'今天':row.task.date.slice(5))+(row.task.time?' '+row.task.time:''):'')+((row.task.subtasks||[]).length?'  · '+row.task.subtasks.filter(function(s){return s.done}).length+'/'+row.task.subtasks.length:'')+(row.task.notes?'  ≡':''); font.pixelSize: 10; color: row.task.date&&row.task.date<row.host.today&&!row.task.done?row.colors.error:row.colors.muted }
        }
        Text { text: '★'; visible: row.task.important; color: row.colors.accent; font.pixelSize: 12 }
        Text {
            visible: row.draggable; text: '⠿'; color: row.colors.muted; font.pixelSize: 18
            Layout.preferredWidth: 18; Layout.fillHeight: true
            MouseArea {
                id: grip; objectName: 'taskGrip_'+row.task.id; anchors.fill: parent; cursorShape: Qt.OpenHandCursor
                drag.target: ghost
                onPressed: function(mouse) { var p=grip.mapToItem(row.host,mouse.x,mouse.y);ghost.x=p.x-20;ghost.y=p.y-15 }
                onReleased: ghost.Drag.drop()
            }
        }
    }
    MouseArea { id: mouse; anchors.fill: parent; anchors.leftMargin: 36; anchors.rightMargin: row.draggable?30:4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: row.host.openTask(row.task) }
    Rectangle {
        id: ghost; parent: row.host; width: 170; height: 34; radius: 7; z: 1000
        property var task: row.task
        visible: grip.drag.active
        color: row.colors.selected; border.color: row.colors.accent
        Drag.active: grip.drag.active; Drag.source: ghost; Drag.keys: ['schedule-app-task']; Drag.hotSpot.x: 20; Drag.hotSpot.y: 15
        Text { anchors.fill: parent; anchors.margins: 9; text: row.task.title; textFormat: Text.PlainText; color: row.colors.text; font.pixelSize: 11; elide: Text.ElideRight }
    }
}
