import QtQuick
import "Theme.js" as Theme

IconButton {
    id: control
    property bool up: false
    contentItem: Item {
        implicitWidth: 12
        implicitHeight: 12
        rotation: control.up ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: 120 } }
        Rectangle {
            x: parent.width / 2 - 4
            y: parent.height / 2 - 2
            width: 5
            height: 1.5
            radius: 0.75
            color: control.hovered ? Theme.primary : Theme.muted
            rotation: 45
            transformOrigin: Item.Left
        }
        Rectangle {
            x: parent.width / 2 - 0.5
            y: parent.height / 2 + 1.5
            width: 5
            height: 1.5
            radius: 0.75
            color: control.hovered ? Theme.primary : Theme.muted
            rotation: -45
            transformOrigin: Item.Left
        }
    }
}
