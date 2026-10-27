pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

ColumnLayout {
    id: root

    property var taskStore
    property bool showBackButton: true
    property int slideDirection: 1
    property real maximumDayHeight: 40
    readonly property real dayHeight: Math.max(24, Math.min(maximumDayHeight, (height - 76) / 6))

    signal agendaRequested()
    signal dragActiveChanged(bool active)

    spacing: 6

    RowLayout {
        Layout.fillWidth: true
        spacing: 2

        DragHandler {
            objectName: "calendarMoveHandler"
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: {
                root.dragActiveChanged(active)
                if (active && root.Window.window)
                    root.Window.window.startSystemMove()
            }
        }

        IconButton {
            objectName: "closeCalendarButton"
            visible: root.showBackButton
            text: "‹"
            textSize: 18
            buttonSize: 26
            accessibleName: qsTr("返回")
            tooltip: qsTr("返回")
            onClicked: root.agendaRequested()
        }

        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.taskStore ? root.taskStore.monthLabel : ""
            color: Theme.ink
            font.pixelSize: 19
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        IconButton {
            objectName: "todayButton"
            text: "今天"
            textSize: 10
            buttonSize: 24
            accessibleName: qsTr("回到今天")
            tooltip: qsTr("回到今天")
            onClicked: {
                if (root.taskStore)
                    root.taskStore.goToday()
                root.agendaRequested()
            }
        }

        IconButton {
            objectName: "previousMonthButton"
            text: "‹"
            textSize: 18
            buttonSize: 24
            accessibleName: qsTr("上个月")
            tooltip: qsTr("上个月")
            onClicked: root.goMonth(-1)
        }

        IconButton {
            objectName: "nextMonthButton"
            text: "›"
            textSize: 18
            buttonSize: 24
            accessibleName: qsTr("下个月")
            tooltip: qsTr("下个月")
            onClicked: root.goMonth(1)
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 0

        Repeater {
            model: ["一", "二", "三", "四", "五", "六", "日"]

            Text {
                required property string modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 16
                text: modelData
                color: Theme.subtle
                font.pixelSize: 10
                font.weight: Font.Medium
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true

        Item {
            id: monthLayer
            width: parent.width
            height: parent.height
            x: 0

            GridLayout {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: implicitHeight
                columns: 7
                columnSpacing: 2
                rowSpacing: 2

                Repeater {
                    model: root.taskStore ? root.taskStore.calendarCells : []

                    CalendarDayCell {
                        objectName: "calendarDay" + modelData.date
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: root.dayHeight
                        cellHeight: root.dayHeight
                        onActivated: function(date) {
                            if (!root.taskStore)
                                return
                            root.taskStore.selectDate(date)
                            root.agendaRequested()
                        }
                    }
                }
            }
        }
    }

    ParallelAnimation {
        id: monthEnter

        NumberAnimation {
            target: monthLayer
            property: "opacity"
            from: 0
            to: 1
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }

        NumberAnimation {
            target: monthLayer
            property: "x"
            from: root.slideDirection * 12
            to: 0
            duration: Theme.normal
            easing.type: Easing.OutCubic
        }
    }

    function goMonth(delta) {
        if (!root.taskStore)
            return
        root.slideDirection = delta
        if (root.taskStore.changeMonth(delta))
            monthEnter.restart()
    }
}
