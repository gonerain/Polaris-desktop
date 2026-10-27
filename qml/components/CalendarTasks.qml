pragma ComponentBehavior: Bound

import QtQuick
import Polaris 1.0
import "Theme.js" as Theme

Rectangle {
    id: widget

    implicitWidth: 528
    implicitHeight: 256
    color: Theme.surface
    radius: 12
    border.width: 1
    border.color: Theme.border
    clip: true

    property bool calendarVisible: false
    readonly property var taskStore: store

    CalendarTaskStore {
        id: store
        objectName: "calendarTaskStore"
    }

    Item {
        anchors.fill: parent
        anchors.margins: 18

        AgendaPanel {
            id: agendaPanel
            objectName: "agendaPanel"
            anchors.fill: parent
            visible: !widget.calendarVisible
            taskStore: store
            onCalendarRequested: widget.calendarVisible = true
        }

        CalendarMonthView {
            objectName: "calendarMonthView"
            anchors.fill: parent
            visible: widget.calendarVisible
            taskStore: store
            onAgendaRequested: widget.calendarVisible = false
        }
    }
}
