import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: row
    required property var host
    required property var event
    readonly property var colors: host.appearance
    implicitHeight: content.implicitHeight + 14
    radius: 7
    color: mouse.containsMouse ? colors.selected : colors.raised
    Rectangle { x: 0; y: 7; width: 3; height: parent.height - 14; radius: 1; color: row.event.color }
    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8; leftMargin: 12 }
        spacing: 2
        Text { Layout.fillWidth: true; text: row.event.title; textFormat: Text.PlainText; color: row.colors.text; font.pixelSize: 12; elide: Text.ElideRight }
        Text { Layout.fillWidth: true; text: row.event.startDate + ' ' + row.event.timeLabel + ' · ' + row.event.calendarTitle; textFormat: Text.PlainText; color: row.colors.muted; font.pixelSize: 10; elide: Text.ElideRight }
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: row.host.openEvent(row.event) }
    Accessible.role: Accessible.Button
    Accessible.name: event.title + ' ' + event.timeLabel
    Accessible.onPressAction: host.openEvent(event)
}
