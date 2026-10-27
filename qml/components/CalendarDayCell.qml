pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

AbstractButton {
    id: cell

    required property var modelData
    readonly property bool editBoundary: true
    property real cellHeight: 28
    signal activated(string date)

    implicitHeight: cellHeight
    enabled: modelData.date !== ""
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    padding: 0
    Accessible.role: Accessible.Button
    Accessible.name: modelData.date

    onClicked: cell.activated(modelData.date)

    scale: down ? 0.94 : 1
    Behavior on scale {
        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
    }

    contentItem: Item {
        readonly property real circleSize: Math.min(30, cell.cellHeight - 5)
        readonly property real circleTop: Math.max(1, (cell.cellHeight - circleSize - 4) / 2)

        Rectangle {
            id: circle
            width: parent.circleSize
            height: width
            radius: width / 2
            anchors.top: parent.top
            anchors.topMargin: parent.circleTop
            anchors.horizontalCenter: parent.horizontalCenter
            color: cell.modelData.selected
                ? Theme.primary
                : cell.hovered
                    ? Theme.primarySoft
                    : cell.modelData.today
                        ? Theme.accentSoft
                        : "transparent"
            border.width: cell.modelData.today && !cell.modelData.selected ? 1 : 0
            border.color: Theme.accent

            Behavior on color {
                ColorAnimation { duration: Theme.fast }
            }
        }

        Text {
            anchors.centerIn: circle
            text: cell.modelData.day
            color: cell.modelData.selected
                ? "white"
                : cell.modelData.today
                    ? Theme.accent
                    : cell.modelData.inMonth
                        ? Theme.ink
                        : Theme.subtle
            font.pixelSize: cell.cellHeight >= 34 ? 14 : 12
            font.weight: cell.modelData.selected || cell.modelData.today ? Font.DemiBold : Font.Normal

            Behavior on color {
                ColorAnimation { duration: Theme.fast }
            }
        }

        Row {
            anchors.top: circle.bottom
            anchors.topMargin: 1
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 2

            Repeater {
                model: Math.min(3, cell.modelData.openCount)

                Rectangle {
                    width: 3
                    height: 3
                    radius: 1.5
                    color: cell.modelData.selected ? Theme.primaryDark : Theme.primary
                    opacity: cell.modelData.inMonth ? 0.9 : 0.4
                }
            }

            Rectangle {
                visible: cell.modelData.openCount === 0 && cell.modelData.taskCount > 0
                width: 3
                height: 3
                radius: 1.5
                color: Theme.success
                opacity: cell.modelData.inMonth ? 0.9 : 0.4
            }
        }
    }
}
