pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    required property var taskStore
    readonly property var presentation: parent.presentationContext
    color: Theme.surface
    radius: 12
    border.color: Theme.border
    border.width: 1
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 18
        RowLayout {
            Layout.fillWidth: true
            IconButton {
                objectName: "focusBackButton"
                text: "←"
                buttonSize: 32
                accessibleName: qsTr("返回画布")
                tooltip: qsTr("返回画布 · Esc")
                onClicked: root.presentation.close()
            }
            Text {
                text: qsTr("日程总览")
                color: Theme.ink
                font.pixelSize: 20
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: root.width >= 760 ? 2 : 1
            columnSpacing: 28
            rowSpacing: 18
            CalendarMonthView {
                objectName: "focusCalendar"
                taskStore: root.taskStore
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 240
            }
            AgendaPanel {
                objectName: "focusAgenda"
                showCalendarButton: false
                taskStore: root.taskStore
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 240
            }
        }
    }
}
