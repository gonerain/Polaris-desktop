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

    EditDismissArea { anchors.fill: parent }

    property bool calendarVisible: false
    required property var taskStore
    readonly property var store: taskStore
    signal dragActiveChanged(bool active)
    signal focusRequested(var factory, var options, var properties)

    Component {
        id: fullViewFactory
        CalendarFocusView { }
    }

    StoreStatus {
        id: status
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 12
        height: implicitHeight
        taskStore: store
    }

    Item {
        anchors.fill: parent
        anchors.margins: 18
        anchors.bottomMargin: status.visible ? status.height + 20 : 18

        AgendaPanel {
            id: agendaPanel
            objectName: "agendaPanel"
            canvasManaged: true
            anchors.fill: parent
            visible: !widget.calendarVisible
            taskStore: store
            showFocusButton: true
            onFocusRequested: widget.focusRequested(fullViewFactory,
                {span: Qt.size(5, 3)}, {taskStore: store})
            onInboxRequested: widget.focusRequested(fullViewFactory,
                {span: Qt.size(5, 3)}, {taskStore: store, mode: "inbox"})
            onCalendarRequested: widget.calendarVisible = true
            onDragActiveChanged: function(active) { widget.dragActiveChanged(active) }
        }

        CalendarMonthView {
            objectName: "calendarMonthView"
            canvasManaged: true
            anchors.fill: parent
            visible: widget.calendarVisible
            taskStore: store
            onAgendaRequested: widget.calendarVisible = false
            onDragActiveChanged: function(active) { widget.dragActiveChanged(active) }
        }
    }
}
