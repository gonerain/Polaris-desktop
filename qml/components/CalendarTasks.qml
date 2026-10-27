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
    signal dragActiveChanged(bool active)
    signal focusRequested(var factory, var options, var properties)

    Component {
        id: fullViewFactory
        CalendarFocusView { }
    }

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
            showFocusButton: true
            onFocusRequested: widget.focusRequested(fullViewFactory,
                {span: Qt.size(4, 3)}, {taskStore: store})
            onCalendarRequested: widget.calendarVisible = true
            onDragActiveChanged: function(active) { widget.dragActiveChanged(active) }
        }

        CalendarMonthView {
            objectName: "calendarMonthView"
            anchors.fill: parent
            visible: widget.calendarVisible
            taskStore: store
            onAgendaRequested: widget.calendarVisible = false
            onDragActiveChanged: function(active) { widget.dragActiveChanged(active) }
        }
    }
}
