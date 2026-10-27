pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    required property var taskStore
    readonly property var presentation: parent.presentationContext
    property bool listMode: false
    readonly property bool escapeBlocked: !listMode && agenda.composerOpen
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
            Rectangle {
                implicitWidth: tabs.implicitWidth + 6
                implicitHeight: 38
                radius: 10
                color: Theme.background
                RowLayout {
                    id: tabs
                    anchors.centerIn: parent
                    spacing: 4
                    IconButton {
                        text: qsTr("日历")
                        textSize: 12
                        buttonSize: 32
                        filled: !root.listMode
                        accessibleName: qsTr("日历视图")
                        onClicked: root.listMode = false
                    }
                    IconButton {
                        objectName: "overviewModeButton"
                        text: qsTr("待办")
                        textSize: 12
                        buttonSize: 32
                        filled: root.listMode
                        accessibleName: qsTr("所有日期的待办")
                        onClicked: root.listMode = true
                    }
                }
            }
        }
        TaskOverview {
            objectName: "taskOverview"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.listMode
            taskStore: root.taskStore
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.listMode
            columns: root.width >= 760 ? 2 : 1
            columnSpacing: 28
            rowSpacing: 18
            CalendarMonthView {
                objectName: "focusCalendar"
                showBackButton: false
                maximumDayHeight: 80
                taskStore: root.taskStore
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 240
            }
            AgendaPanel {
                id: agenda
                objectName: "focusAgenda"
                showCalendarButton: false
                taskStore: root.taskStore
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 240
            }
        }
        StoreStatus {
            Layout.fillWidth: true
            taskStore: root.taskStore
            showSavedHint: true
        }
    }
}
